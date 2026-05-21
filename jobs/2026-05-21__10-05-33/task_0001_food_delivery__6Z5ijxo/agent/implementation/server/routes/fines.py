from flask import Blueprint, request

from ..auth import require_role
from ..envelope import success, list_ok
from ..errors import err
from ..pagination import parse_limit_offset, paginate
from ..repository import body_or_empty
from ..store import store
from ..domain.fines import waive_fine

bp = Blueprint("fines", __name__)

_VALID_SUBJECT_TYPES = {"RIDER", "RESTAURANT", "CUSTOMER"}
_VALID_SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "WAIVED"}


def _view(f):
    return {k: f.get(k) for k in (
        "id", "subject_type", "subject_id", "reason", "amount_cents",
        "settlement_status",
        "related_order_id", "related_return_id", "related_assignment_id",
        "created_at",
    )}


@bp.get("/api/fines/<fid>")
def get_fine(fid):
    uid, role = require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    f = store.fines.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", "fine not found")
    if role == "Rider" and not (f["subject_type"] == "RIDER" and f["subject_id"] == uid):
        raise err("ERR_FORBIDDEN", "not your fine")
    if role == "Restaurant" and not (f["subject_type"] == "RESTAURANT" and f["subject_id"] == uid):
        raise err("ERR_FORBIDDEN", "not your fine")
    if role == "Customer" and not (f["subject_type"] == "CUSTOMER" and f["subject_id"] == uid):
        raise err("ERR_FORBIDDEN", "not your fine")
    return success(_view(f))


@bp.get("/api/fines")
def list_fines():
    uid, role = require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    limit, offset = parse_limit_offset()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    if subject_type and subject_type not in _VALID_SUBJECT_TYPES:
        raise err("ERR_VALIDATION", "invalid subject_type")
    if settlement_status and settlement_status not in _VALID_SETTLEMENT_STATUSES:
        raise err("ERR_VALIDATION", "invalid settlement_status")
    # Non-CS/Admin roles must filter by their own subject_id and matching type
    role_to_subject_type = {"Rider": "RIDER", "Restaurant": "RESTAURANT", "Customer": "CUSTOMER"}
    if role in role_to_subject_type:
        expected_type = role_to_subject_type[role]
        if subject_id != uid:
            raise err("ERR_FORBIDDEN", "can only query your own subject_id")
        if subject_type and subject_type != expected_type:
            raise err("ERR_FORBIDDEN", "subject_type mismatch for role")
        subject_type = expected_type
    items = list(store.fines.values())
    if subject_type:
        items = [f for f in items if f["subject_type"] == subject_type]
    if subject_id:
        items = [f for f in items if f["subject_id"] == subject_id]
    if settlement_status:
        items = [f for f in items if f["settlement_status"] == settlement_status]
    items.sort(key=lambda x: x["created_at"])
    window, total = paginate(items, limit, offset)
    return list_ok([_view(x) for x in window], limit, offset, total)


@bp.post("/api/fines/<fid>/waive")
def waive_fine_endpoint(fid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    f = store.fines.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", "fine not found")
    if f["settlement_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "fine not in PENDING")
    body_or_empty()
    # Ledger reversal mutates the subject — we need to touch the subject too.
    waive_fine(f)
    # Touch the subject so version increments
    if f["subject_type"] == "RIDER":
        rider = store.riders.get(f["subject_id"])
        if rider is not None:
            from ..repository import touch
            touch(rider)
    elif f["subject_type"] == "CUSTOMER":
        c = store.customers.get(f["subject_id"])
        if c is not None:
            from ..repository import touch
            touch(c)
    elif f["subject_type"] == "RESTAURANT":
        r = store.restaurants.get(f["subject_id"])
        if r is not None:
            from ..repository import touch
            touch(r)
    return success(_view(f))
