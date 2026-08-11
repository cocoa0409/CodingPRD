"""Customer endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.common import (
    new_entity, touch, get_customer, check_ownership,
)
from services.serializers import serialize_customer, serialize_credit_ledger_entry

bp = Blueprint("customers", __name__)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/customers")
def create_customer():
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin", "ShopManager"})
    data = _body()
    full_name = data.get("full_name")
    email = data.get("email")
    if not isinstance(full_name, str) or not full_name.strip():
        raise_err("ERR_VALIDATION", "full_name is required")
    if not isinstance(email, str) or not email.strip():
        raise_err("ERR_VALIDATION", "email is required")
    for existing in db.customers.values():
        if existing["email"] == email:
            raise_err("ERR_VALIDATION", "email must be unique across customers")
    c = new_entity()
    c.update({
        "full_name": full_name,
        "email": email,
        "status": "ACTIVE",
        "completed_builds_count": 0,
        "credit_balance_cents": 0,
    })
    db.customers[c["id"]] = c
    return success_response(serialize_customer(c), status=201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin", "ShopManager", "FittingSpecialist",
                        "RepairTechnician", "Instructor", "Customer"})
    c = get_customer(cid)
    check_ownership(c, user_id, role)
    return success_response(serialize_customer(c))


@bp.post("/customers/<cid>/set-status")
def set_customer_status(cid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    target_status = data.get("target_status")
    if target_status not in ("ACTIVE", "SUSPENDED"):
        raise_err("ERR_VALIDATION", "target_status must be ACTIVE or SUSPENDED")
    c = get_customer(cid)
    c["status"] = target_status
    touch(c)
    return success_response(serialize_customer(c))


@bp.get("/customers/<cid>/credit-ledger-entries")
def list_credit_ledger(cid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "ShopManager"})
    c = get_customer(cid)
    check_ownership(c, user_id, role)
    limit, offset = parse_pagination(request.args)
    entries = [e for e in db.credit_ledger_entries if e["customer_id"] == cid]
    entries.sort(key=lambda e: e["created_at"])
    page, pagination = apply_pagination(entries, limit, offset)
    return success_response(
        [serialize_credit_ledger_entry(e) for e in page],
        response_type="array", pagination=pagination,
    )
