"""Admin test-driving endpoints: /_clock/set_current_utc and /_payments/simulate."""

from flask import Blueprint

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    to_iso = util.get_iso_datetime(body, "to_iso8601")
    cur = db.get_now()
    if to_iso < cur:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "clock must be monotonically non-decreasing")
    db.set_now(to_iso)
    return resp.ok({"current_utc": db.format_iso(to_iso)})


@bp.route("/_payments/simulate", methods=["POST"])
def simulate_payment():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    order_id = util.get_str(body, "order_id")
    amount = util.get_int(body, "amount_cents")
    outcome = util.get_enum(body, "outcome", ["SUCCEEDED", "FAILED"])
    o = models.get_order(order_id)

    if o["status"] in ("DELIVERED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] != "DEPOSIT_PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE, "order is not in DEPOSIT_PENDING")

    if outcome != "SUCCEEDED":
        return resp.ok(o)

    if amount != int(o["deposit_due_cents"]):
        errors.raise_error(errors.ERR_DEPOSIT_NOT_PAID, "amount must equal deposit_due_cents")

    if o.get("deposit_paid_at") is not None:
        errors.raise_error(errors.ERR_INVALID_STATE, "deposit already fully paid")

    o["deposit_paid_cents"] = int(o["deposit_paid_cents"]) + amount
    if o["deposit_paid_cents"] == int(o["deposit_due_cents"]):
        o["deposit_paid_at"] = db.iso_now()
        c = db.customers.get(o["customer_id"])
        if c:
            c["cumulative_deposits_paid_cents"] = int(c.get("cumulative_deposits_paid_cents", 0)) + amount
            models.bump(c)
    services.recompute_order_total(o)
    models.bump(o)
    services.try_cascade_deposit_and_approval(o)
    return resp.ok(o)
