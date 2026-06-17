"""Warranty claims + the test-driving clock."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles, require_owner
from helpers import (base_record, get_body, require_string, get_work_order_or_404,
                     get_resource_or_404, parse_pagination, paginate, touch,
                     serialize, serialize_list)
from response import ok_object, ok_array
import calculations as calc

bp = Blueprint("warranty", __name__)


def _parse_iso_epoch(value):
    """Parse an ISO 8601 instant to epoch seconds (float)."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# --------------------------------------------------------------------------
# Test-driving clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    to_iso = require_string(body, "to_iso8601")
    _parse_iso_epoch(to_iso)  # validate parseable
    db.clock_override = to_iso
    return ok_object({}, 200)


# --------------------------------------------------------------------------
# Warranty claims
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/warranty-claims")
def file_claim(wid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    wo = get_work_order_or_404(wid)
    require_owner(user_id, wo)
    body = get_body()
    defect_note = require_string(body, "defect_note")
    filed_at = require_string(body, "filed_at")

    # Only on a COMPLETED order (priority 60).
    if wo["status"] != "COMPLETED":
        raise err(errors.ERR_ORDER_NOT_COMPLETED,
                  "Warranty claim may only be filed on a COMPLETED order")

    filed_epoch = _parse_iso_epoch(filed_at)
    completed_epoch = _parse_iso_epoch(wo["completed_at"])
    covered = calc.warranty_covered(True, completed_epoch, filed_epoch)

    rec = base_record(common=True)
    rec.update({
        "work_order_id": wid,
        "defect_note": defect_note,
        "filed_at": filed_at,
        "covered": covered,
        "status": "OPEN",
    })
    db.warranty_claims[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/warranty-claims/<cid>")
def get_claim(cid):
    _, role = get_identity()
    require_roles(role, {"Customer", "ShopManager"})
    rec = get_resource_or_404(db.warranty_claims, cid)
    return ok_object(serialize(rec), 200)


@bp.get("/work-orders/<wid>/warranty-claims")
def list_claims(wid):
    _, role = get_identity()
    require_roles(role, {"Customer", "ShopManager", "Estimator"})
    limit, offset = parse_pagination()
    get_work_order_or_404(wid)
    matches = [c for c in db.warranty_claims.values() if c["work_order_id"] == wid]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/warranty-claims/<cid>/approve")
def approve_claim(cid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.warranty_claims, cid)
    if rec["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Claim must be OPEN to approve")
    if not rec["covered"]:
        raise err(errors.ERR_INVALID_STATE,
                  "An out-of-window (uncovered) claim cannot be approved")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/warranty-claims/<cid>/deny")
def deny_claim(cid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.warranty_claims, cid)
    if rec["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Claim must be OPEN to deny")
    rec["status"] = "DENIED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/warranty-claims/<cid>/resolve")
def resolve_claim(cid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.warranty_claims, cid)
    if rec["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "Claim must be APPROVED to resolve")
    rec["status"] = "RESOLVED"
    touch(rec)
    return ok_object(serialize(rec), 200)
