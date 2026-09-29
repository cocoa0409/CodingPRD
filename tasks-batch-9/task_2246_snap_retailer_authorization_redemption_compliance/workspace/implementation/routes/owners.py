"""Logical clock and Owner endpoints."""
from flask import Blueprint

import serial
from core import (clock, db, ensure_object, filter_str, get_body, ok, ok_list,
                  ordered, paginate, req_dt, req_enum, req_str, require_auth,
                  resolve_path, stamp_new)
from guards import ADMIN, ALL_READ

bp = Blueprint("owners", __name__)

OWNERSHIP_TYPES = ("SOLE_PROPRIETOR", "PARTNERSHIP", "CORPORATION", "LLC")
SANCTION_FLAGS = ("CLEAR", "HAS_ACTIVE_CMP_DEBT", "PERMANENTLY_DISQUALIFIED")
OWNER_STATUSES = ("ACTIVE", "BARRED")


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    clock.set(req_dt(body, "current_utc"))
    return ok({})


@bp.post("/owners")
def create_owner():
    require_auth(("Anonymous", "FnsAdmin"), anonymous_allowed=True)
    body = get_body()
    ensure_object(body)
    legal_name = req_str(body, "legal_name")
    ownership_type = req_enum(body, "ownership_type", OWNERSHIP_TYPES)
    tax_id_last4 = req_str(body, "tax_id_last4")
    if len(tax_id_last4) != 4:
        from core import bad_request
        bad_request("Field 'tax_id_last4' must be exactly 4 characters.")
    row = stamp_new({
        "legal_name": legal_name,
        "ownership_type": ownership_type,
        "tax_id_last4": tax_id_last4,
        "permanent_disqualification_count": 0,
        "cmp_outstanding_cents": 0,
        "sanction_flag": "CLEAR",
        "status": "ACTIVE",
    })
    db.owners[row["id"]] = row
    return ok(serial.owner(row), 201)


@bp.get("/owners/<owner_id>")
def get_owner(owner_id):
    require_auth(ALL_READ)
    row = resolve_path(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")
    return ok(serial.owner(row))


@bp.get("/owners")
def list_owners():
    require_auth(("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer"))
    rows = ordered(list(db.owners.values()))
    sanction_flag = filter_str("sanction_flag")
    status = filter_str("status")
    if sanction_flag is not None:
        rows = [r for r in rows if r["sanction_flag"] == sanction_flag]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, pagination = paginate(rows, serial.owner)
    return ok_list(data, pagination)
