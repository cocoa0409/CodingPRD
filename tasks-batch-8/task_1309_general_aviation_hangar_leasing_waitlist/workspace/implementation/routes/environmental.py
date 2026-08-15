"""EnvironmentalComplianceRecord endpoints."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND
from routes.leases import get_lease_or_404
from services.core import RECORD_TYPES, touch
from timeutil import iso_z
from validators import body, paginate, pagination, req_dt, req_enum, req_str

bp = Blueprint("environmental", __name__)


@bp.post("/leases/<lid>/environmental-records")
def create_env_record(lid):
    uid, _role = require_roles("Tenant")
    lease = get_lease_or_404(lid)
    require_ownership(lease["id"], uid)
    data = body()
    record_type = req_enum(data, "record_type", RECORD_TYPES)
    expires_at = req_dt(data, "expires_at")
    record = db.new_entity({
        "lease_id": lease["id"],
        "record_type": record_type,
        "submitted_at": iso_z(db.clock_now()),
        "expires_at": iso_z(expires_at),
        "review_note": "",
        "status": "PENDING_REVIEW",
    })
    db.env_records[record["id"]] = record
    return success_obj(db.public(record), 201)


@bp.get("/leases/<lid>/environmental-records")
def list_env_records(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [r for r in db.env_records.values() if r["lease_id"] == lease["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total)


def _review(rid, outcome):
    require_roles("ComplianceOfficer")
    record = db.env_records.get(rid)
    if record is None:
        raise ApiError(ERR_NOT_FOUND, "Environmental record not found", 404)
    if record["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Record must be PENDING_REVIEW", 409)
    data = body()
    note = req_str(data, "review_note")
    record["status"] = outcome
    record["review_note"] = note
    touch(record)
    return success_obj(db.public(record), 200)


@bp.post("/environmental-records/<rid>/approve")
def approve_env_record(rid):
    return _review(rid, "APPROVED")


@bp.post("/environmental-records/<rid>/reject")
def reject_env_record(rid):
    return _review(rid, "REJECTED")
