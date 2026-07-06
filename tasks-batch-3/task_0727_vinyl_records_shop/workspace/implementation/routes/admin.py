"""Test-driving admin endpoints: logical clock, loyalty adjustment."""
from flask import Blueprint

import db
from models import touch
from middleware import authenticate
from validators import get_body, require_string, require_int, lookup
from response import success
from errors import err, ERR_INVALID_REQUEST
from services import public, recompute_tier

bp = Blueprint("admin", __name__)


@bp.route("/shop/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"Manager"})
    body = get_body()
    to_iso = require_string(body, "to_iso8601")
    try:
        db.db.set_clock(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Invalid to_iso8601")
    return success({"current_utc": db.now_iso()}, 200)


@bp.route("/shop/_loyalty/adjust-points", methods=["POST"])
def adjust_points():
    authenticate({"Manager"})
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise err(ERR_INVALID_REQUEST, "customer_id required")
    delta = require_int(body, "delta_points")
    cust = lookup(db.db.customers, customer_id)
    cust["loyalty_points"] += delta
    if cust["loyalty_points"] < 0:
        cust["loyalty_points"] = 0
    recompute_tier(cust)
    touch(cust)
    return success(public(cust), 200)
