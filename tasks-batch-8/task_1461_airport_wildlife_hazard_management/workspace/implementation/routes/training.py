"""Training records: record, list, revoke."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles
from constants import TRAINING_STATUSES
from db import store
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, parse_date)

bp = Blueprint("training", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")


@bp.post("/training-records")
def create_training():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("biologist_id", "str", True),
        ("course_code", "str", True),
        ("completed_at", "date", True),
        ("expires_at", "date", True),
    ])
    check_fk("biologist_id", data["biologist_id"], store.biologists, "biologist")
    if not parse_date(data["completed_at"]) < parse_date(data["expires_at"]):
        raise E.ApiError(E.ERR_INVALID_WINDOW,
                         "expires_at must be strictly after completed_at", 422)
    rec = new_entity(store.training_records, {
        "biologist_id": data["biologist_id"],
        "course_code": data["course_code"],
        "completed_at": data["completed_at"],
        "expires_at": data["expires_at"],
        "status": "VALID",
    })
    return ok_object(serialize(rec), 201)


@bp.get("/training-records")
def list_training():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    if status is not None and status not in TRAINING_STATUSES:
        raise E.invalid_enum("status", status)
    rows = [t for t in store.training_records.values()
            if (args.get("biologist_id") is None or t["biologist_id"] == args.get("biologist_id"))
            and (status is None or t["status"] == status)
            and (args.get("course_code") is None or t["course_code"] == args.get("course_code"))]
    return list_response(rows)


@bp.get("/training-records/<rid>")
def get_training(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(get_or_404(store.training_records, rid, "training record")))


@bp.post("/training-records/<rid>/revoke")
def revoke_training(rid):
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    rec = get_or_404(store.training_records, rid, "training record")
    if rec["status"] != "VALID":
        raise E.invalid_state("training record must be in VALID to revoke")
    rec["status"] = "REVOKED"
    touch(rec)
    return ok_object(serialize(rec))
