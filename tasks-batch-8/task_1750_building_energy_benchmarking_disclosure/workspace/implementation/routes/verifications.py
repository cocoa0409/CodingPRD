"""Verification record endpoints: assign, sign-off, reject, list, get."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import json_object, parse_body, require_path_entity, require_min_length
from validation import validate_schema

bp = Blueprint("verifications", __name__)


@bp.post("/v1/benchmark-reports/<report_id>/verification-records")
def create_verification_record(report_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    report = require_path_entity(store.reports, report_id)
    building = store.buildings.get(report["building_id"])
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this report's building")
    body = json_object()
    verifier = None
    if isinstance(body.get("verifier_id"), str):
        verifier = store.verifiers.get(body["verifier_id"])
        if verifier is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced verifier does not exist")
    if verifier is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "verifier_id is required")
    validate_schema(body, {"verifier_id": ("string", True, None)})
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "A verifier can only be assigned to a SUBMITTED report")
    for vr in store.verification_records.values():
        if vr["report_id"] == report["id"] and vr["status"] == "PENDING":
            raise ApiError("ERR_VERIFIER_ALREADY_ASSIGNED", 409,
                           "A PENDING verification record already exists for this report")
    record = db.new_common({
        "id": db.new_id(),
        "report_id": report["id"],
        "verifier_id": verifier["id"],
        "status": "PENDING",
        "decided_at": None,
        "rejection_reason": None,
    })
    store.verification_records[record["id"]] = record
    return created(record)


@bp.post("/v1/verification-records/<record_id>/sign-off")
def sign_off(record_id):
    uid, _ = get_context()
    require_roles(["DataVerifier"])
    record = require_path_entity(store.verification_records, record_id)
    if record["verifier_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "DataVerifier is not the assigned verifier for this record")
    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PENDING verification record can be signed off")
    report = store.reports.get(record["report_id"])
    if report is None or report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "The report must be SUBMITTED for sign-off")
    building = store.buildings.get(report["building_id"])
    cycle = store.cycles.get(report["cycle_id"])
    std = core.perf_std(cycle, building["property_type"])
    if std is None:
        raise ApiError("ERR_STANDARD_NOT_DEFINED", 422,
                       "The cycle has no performance standard for this property type")
    record["status"] = "SIGNED_OFF"
    record["decided_at"] = db.LOGICAL_CLOCK
    db.touch(record)
    core.verify_report(report, cycle, building, std)
    return ok(record)


@bp.post("/v1/verification-records/<record_id>/reject")
def reject(record_id):
    uid, _ = get_context()
    require_roles(["DataVerifier"])
    record = require_path_entity(store.verification_records, record_id)
    if record["verifier_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "DataVerifier is not the assigned verifier for this record")
    body = parse_body({"rejection_reason": ("string", True, None)}, allow_empty=False)
    require_min_length(body, "rejection_reason", 10)
    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PENDING verification record can be rejected")
    record["status"] = "REJECTED"
    record["decided_at"] = db.LOGICAL_CLOCK
    record["rejection_reason"] = body["rejection_reason"]
    db.touch(record)
    report = store.reports.get(record["report_id"])
    if report is not None:
        report["status"] = "FLAGGED"
        db.touch(report)
        core.create_anomaly(report["id"], "VERIFICATION_FAILED",
                            "Verifier rejected the report: %s" % body["rejection_reason"])
    return ok(record)


@bp.get("/v1/verification-records")
def list_verification_records():
    get_context()
    rows = list(store.verification_records.values())
    rows = paginate.filter(rows, "report_id")
    rows = paginate.filter(rows, "verifier_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/verification-records/<record_id>")
def get_verification_record(record_id):
    get_context()
    record = require_path_entity(store.verification_records, record_id)
    return ok(record)
