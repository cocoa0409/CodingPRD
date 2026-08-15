"""Customer endpoints."""

from flask import Blueprint

import db
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    get_customer_or_404,
    get_json_body,
    mint_id,
    opt_int,
    opt_str,
    paginate,
    pagination_params,
    req_int,
    req_str,
    serialize_customer,
    stamp_now,
)
import errors as E
from errors import ApiError

bp = Blueprint("customers", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


@bp.post("/customers")
def create_customer():
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    name = req_str(body, "name")
    credit_limit_cents = req_int(body, "credit_limit_cents")
    open_balance_cents = opt_int(body, "open_balance_cents", 0)
    trailing_purchases = opt_int(body, "trailing_12mo_purchases_cents", 0)
    trailing_usage = opt_int(body, "trailing_12mo_component_usage_units", 0)
    status = opt_str(body, "status", "GOOD_STANDING")
    if status not in ("GOOD_STANDING", "CREDIT_HOLD"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid status.")

    now = stamp_now()
    customer = {
        "id": mint_id(),
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "open_balance_cents": open_balance_cents,
        "trailing_12mo_purchases_cents": trailing_purchases,
        "trailing_12mo_component_usage_units": trailing_usage,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.customers[customer["id"]] = customer
    return success(serialize_customer(customer), status=201)


@bp.get("/customers")
def list_customers():
    require_auth()
    limit, offset = pagination_params()
    items = sorted(db.customers.values(), key=lambda c: (c["created_at"], c["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_customer(c) for c in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/customers/<customerId>")
def get_customer(customerId):
    require_auth()
    customer = get_customer_or_404(customerId)
    return success(serialize_customer(customer), status=200)
