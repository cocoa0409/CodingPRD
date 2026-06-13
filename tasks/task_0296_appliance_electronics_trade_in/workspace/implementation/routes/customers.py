"""Customer routes (PRD 3.3)."""
from flask import Blueprint

from db import db
from errors import err, ERR_DUPLICATE
from middleware import get_principal, require_role
from models import new_record, serialize, sort_by_created
from reqs import get_json_body, req_str, parse_pagination, paginate
from response import object_response, array_response
from services.lookups import get_customer_or_404

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "Customer"})
    body = get_json_body()

    email = req_str(body, "email")
    full_name = req_str(body, "full_name")

    # Unique email, case-insensitive.
    for c in db.customers.values():
        if c["email"].lower() == email.lower():
            raise err(ERR_DUPLICATE, "email already registered")

    rec = new_record("Customer", {
        "email": email,
        "full_name": full_name,
        "wallet_balance_cents": 0,
        "lifetime_payout_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "Customer"})
    rec = get_customer_or_404(cid)
    return object_response(serialize(rec))


@bp.route("/customers/<cid>/trade-ins", methods=["GET"])
def list_customer_trade_ins(cid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "Customer"})
    get_customer_or_404(cid)
    limit, offset = parse_pagination()

    items = [t for t in db.trade_ins.values() if t["customer_id"] == cid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(t) for t in page], limit, offset, total)
