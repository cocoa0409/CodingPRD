"""Inspection endpoints: create (OCC on hydrant), list, get, record, verify."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_HYDRANT_NOT_FOUND,
    ERR_HYDRANT_OWNERSHIP_MISMATCH,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_PENDING_VERIFICATION,
    ERR_INSPECTION_NOT_RECORDABLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import inspection_view
from services import recompute_tier
from validation import F, paginate, validate_body

bp = Blueprint("inspections", __name__)


def get_inspection_or_404(inspection_id):
    i = db.store.inspections.get(inspection_id)
    if i is None:
        raise not_found(ERR_INSPECTION_NOT_FOUND, "Inspection")
    return i


@bp.post("/inspections")
def create_inspection():
    user_id, role = auth()
    body = validate_body([
        F("hydrant_id", "str"),
        F("scheduled_date", "datetime"),
        F("expected_hydrant_version", "int"),
    ])
    require_role(role, {"FieldOperator"})
    hydrant = db.store.hydrants.get(body["hydrant_id"])
    if hydrant is None:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    # OCC: expected_hydrant_version must match the hydrant's current version
    if body["expected_hydrant_version"] != hydrant["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_hydrant_version does not match the hydrant's current version",
            412,
        )
    inspection = new_base()
    inspection.update({
        "hydrant_id": hydrant["id"],
        "scheduled_date": body["scheduled_date"],
        "status": "SCHEDULED",
        "performed_date": None,
        "defects_found": None,
        "condition_notes": "",
        "performed_by_user_id": None,
        "verified_by_user_id": None,
        "result": "NONE",
    })
    db.store.inspections[inspection["id"]] = inspection
    hydrant["latest_inspection_id"] = inspection["id"]
    touch(hydrant)
    return success_object(inspection_view(inspection), code=201)


@bp.get("/inspections")
def list_inspections():
    auth_any()
    items = list(db.store.inspections.values())
    hydrant_id = request.args.get("hydrant_id")
    if hydrant_id is not None:
        items = [i for i in items if i["hydrant_id"] == hydrant_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, meta = paginate(items)
    return success_list([inspection_view(i) for i in page], meta)


@bp.get("/inspections/<inspection_id>")
def get_inspection(inspection_id):
    auth_any()
    return success_object(inspection_view(get_inspection_or_404(inspection_id)))


@bp.post("/inspections/<inspection_id>/record")
def record_inspection(inspection_id):
    user_id, role = auth()
    body = validate_body([
        F("performed_date", "datetime"),
        F("defects_found", "bool"),
        F("condition_notes", "str", required=False, default=""),
    ])
    require_role(role, {"FieldOperator", "PrivateOwnerRep"})
    inspection = get_inspection_or_404(inspection_id)
    hydrant = db.store.hydrants[inspection["hydrant_id"]]
    # Ownership scope (priority 4): MUNICIPAL requires FieldOperator; PRIVATE
    # requires a PrivateOwnerRep whose X-User-ID equals hydrant.private_owner_id
    if hydrant["ownership"] == "MUNICIPAL":
        if role != "FieldOperator":
            raise ApiError(
                ERR_HYDRANT_OWNERSHIP_MISMATCH,
                "MUNICIPAL hydrant inspections must be recorded by a FieldOperator",
                403,
            )
    else:
        if role != "PrivateOwnerRep" or user_id != hydrant["private_owner_id"]:
            raise ApiError(
                ERR_HYDRANT_OWNERSHIP_MISMATCH,
                "PRIVATE hydrant inspections must be recorded by its owner's representative",
                403,
            )
    if inspection["status"] not in ("SCHEDULED", "REJECTED"):
        raise ApiError(
            ERR_INSPECTION_NOT_RECORDABLE,
            "Inspection must be SCHEDULED or REJECTED to record",
            409,
        )
    inspection["performed_date"] = body["performed_date"]
    inspection["defects_found"] = body["defects_found"]
    inspection["condition_notes"] = body["condition_notes"]
    inspection["performed_by_user_id"] = user_id
    inspection["status"] = "PENDING_VERIFICATION"
    touch(inspection)
    return success_object(inspection_view(inspection))


@bp.post("/inspections/<inspection_id>/verify")
def verify_inspection(inspection_id):
    user_id, role = auth()
    body = validate_body([F("decision", "enum", arg={"VERIFY", "REJECT"})])
    require_role(role, {"UtilitySupervisor"})
    inspection = get_inspection_or_404(inspection_id)
    # Segregation of duties (priority 6) precedes the state precondition (8)
    if inspection["performed_by_user_id"] is not None and user_id == inspection["performed_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Verifier must differ from the performer",
            403,
        )
    if inspection["status"] != "PENDING_VERIFICATION":
        raise ApiError(
            ERR_INSPECTION_NOT_PENDING_VERIFICATION,
            "Inspection must be PENDING_VERIFICATION to verify",
            409,
        )
    inspection["verified_by_user_id"] = user_id
    if body["decision"] == "VERIFY":
        inspection["status"] = "VERIFIED"
        inspection["result"] = "PASS" if inspection["defects_found"] is False else "FAIL"
        touch(inspection)
        hydrant = db.store.hydrants[inspection["hydrant_id"]]
        hydrant["last_verified_inspection_date"] = inspection["performed_date"]
        touch(hydrant)
        recompute_tier(hydrant)  # recomputed from the new baseline
        if inspection["result"] == "FAIL":
            # CASCADE: auto-create a draft repair work order
            wo = new_base()
            wo.update({
                "hydrant_id": hydrant["id"],
                "source_inspection_id": inspection["id"],
                "description": "Auto-generated from failed inspection",
                "budget_cap_cents": None,
                "status": "DRAFT",
                "part_lines": [],
                "quoted_subtotal_cents": None,
                "quoted_discount_cents": None,
                "quoted_fee_cents": None,
                "quoted_total_cents": None,
                "actual_total_cents": None,
                "created_by_user_id": "system",
                "approved_by_user_id": None,
                "last_rejection_reason": None,
            })
            db.store.work_orders[wo["id"]] = wo
    else:
        inspection["status"] = "REJECTED"
        # result stays NONE
        touch(inspection)
    return success_object(inspection_view(inspection))
