"""SafetyInspection endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    apply_overdue_sweep_to_inspection,
    cascade_inspection_result,
    get_agreement_or_404,
    mint_common_fields,
    touch,
)
from util import (
    as_enum,
    as_iso_date,
    as_list,
    as_str,
    body,
    pagination_args,
    required,
)


def _get_inspection_or_404(insp_id):
    i = DB["inspections"].get(insp_id)
    if i is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", 404, "SafetyInspection not found")
    return i


def register(app):
    @app.route("/inspections", methods=["POST"])
    def create_inspection():
        auth(["SafetyInspector"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        segment_id = as_str(required(data, "segment_id"), "segment_id")
        scheduled_date = as_iso_date(required(data, "scheduled_date"), "scheduled_date")

        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)
        segment = DB["segments"].get(segment_id)
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )
        # Cross-FK consistency (priority 11)
        if segment.get("agreement_id") != agreement["id"]:
            raise ApiError(
                "ERR_CROSS_REFERENCE_MISMATCH",
                422,
                "segment_id does not belong to agreement_id",
            )

        insp = {
            "agreement_id": agreement["id"],
            "segment_id": segment["id"],
            "scheduled_date": scheduled_date,
            "due_date": scheduled_date,
            "result": None,
            "completed_date": None,
            "cited_device_ids": [],
            "status": "SCHEDULED",
        }
        mint_common_fields(insp)
        DB["inspections"][insp["id"]] = insp
        return ok(insp, 201)

    @app.route("/inspections", methods=["GET"])
    def list_inspections():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        segment_id = request.args.get("segment_id")
        items = list(DB["inspections"].values())
        if agreement_id is not None:
            items = [i for i in items if i.get("agreement_id") == agreement_id]
        if segment_id is not None:
            items = [i for i in items if i.get("segment_id") == segment_id]
        for i in items:
            apply_overdue_sweep_to_inspection(i)
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/inspections/<inspectionId>", methods=["GET"])
    def get_inspection(inspectionId):
        auth(ALL_ROLES)
        insp = _get_inspection_or_404(inspectionId)
        apply_overdue_sweep_to_inspection(insp)
        return ok(insp)

    @app.route("/inspections/<inspectionId>/record-result", methods=["POST"])
    def record_result(inspectionId):
        auth(["SafetyInspector"])
        insp = _get_inspection_or_404(inspectionId)
        apply_overdue_sweep_to_inspection(insp)
        data = body()
        result = as_enum(required(data, "result"), "result", {"PASS", "FAIL"})
        completed_date = as_iso_date(required(data, "completed_date"), "completed_date")
        cited_device_ids = data.get("cited_device_ids")
        if cited_device_ids is None:
            cited_device_ids = []
        else:
            cited_device_ids = as_list(cited_device_ids, "cited_device_ids")
            for d in cited_device_ids:
                as_str(d, "cited_device_ids[]")

        if insp["status"] not in ("SCHEDULED", "OVERDUE"):
            raise ApiError(
                "ERR_INSPECTION_INVALID_STATE",
                409,
                "Inspection must be SCHEDULED or OVERDUE to record a result",
            )
        # Cross-reference: every cited device must belong to inspection.segment_id
        for dev_id in cited_device_ids:
            dev = DB["derail_devices"].get(dev_id)
            if dev is None or dev.get("segment_id") != insp["segment_id"]:
                raise ApiError(
                    "ERR_CROSS_REFERENCE_MISMATCH",
                    422,
                    "Cited device does not belong to the inspection's segment",
                )

        insp["completed_date"] = completed_date
        insp["result"] = result
        insp["cited_device_ids"] = list(cited_device_ids)
        insp["status"] = "COMPLETED_PASS" if result == "PASS" else "COMPLETED_FAIL"
        touch(insp)
        cascade_inspection_result(insp, result, cited_device_ids)
        return ok(insp)
