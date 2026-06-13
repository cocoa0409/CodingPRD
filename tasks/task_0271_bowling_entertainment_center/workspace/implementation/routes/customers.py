"""Customer registration and lifecycle (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_common, touch
from middleware import get_identity, require_role
from response import success, array
from services import serialize
from services.reservation_sm import suspend_cascade
from services.util import get_body, parse_pagination, paginate, lookup, as_str

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_identity()
    require_role(role, {"FrontDesk", "CenterManager"})
    body = get_body()
    email = as_str(body, "email")
    full_name = as_str(body, "full_name")
    e = new_common()
    e.update({
        "email": email,
        "full_name": full_name,
        "deposit_balance_cents": 0,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[e["id"]] = e
    return success(serialize.customer(e), status=201)


@bp.get("/customers/<id>")
def get_customer(id):
    _, role = get_identity()
    require_role(role, {"CenterManager", "FrontDesk", "Customer"})
    e = lookup(db.customers, id, "customer")
    return success(serialize.customer(e))


@bp.get("/customers")
def list_customers():
    _, role = get_identity()
    require_role(role, {"CenterManager", "FrontDesk"})
    limit, offset = parse_pagination()
    items = list(db.customers.values())
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items, limit, offset)
    return array([serialize.customer(e) for e in page], pagination=meta)


@bp.post("/customers/<id>/suspend")
def suspend_customer(id):
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    e = lookup(db.customers, id, "customer")
    if e["status"] != "ACTIVE":
        # Already suspended — re-suspend is idempotent state-wise; PRD does not
        # define a transition from SUSPENDED, treat as invalid state.
        from errors import err
        raise err("ERR_INVALID_STATE", "Customer is not ACTIVE")
    e["status"] = "SUSPENDED"
    touch(e)
    # CASCADE depth-3: HELD reservations -> EXPIRED (release deposit + return rentals).
    suspend_cascade(e)
    return success(serialize.customer(e))


@bp.post("/customers/<id>/reinstate")
def reinstate_customer(id):
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    e = lookup(db.customers, id, "customer")
    if e["status"] != "SUSPENDED":
        from errors import err
        raise err("ERR_INVALID_STATE", "Customer is not SUSPENDED")
    e["status"] = "ACTIVE"
    touch(e)
    return success(serialize.customer(e))
