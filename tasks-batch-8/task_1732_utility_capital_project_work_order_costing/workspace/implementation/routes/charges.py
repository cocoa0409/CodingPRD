"""CostCharge endpoints (PRD 3.5): posting with overhead loading and the
variance hold; reversals as negative prior-period adjustment rows."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_WORK_ORDER_SUSPENDED, ERR_PERIOD_NOT_FOUND,
    ERR_PERIOD_CLOSED, ERR_OVERHEAD_RATE_NOT_FOUND, ERR_VARIANCE_HOLD,
    ERR_REVERSAL_NOT_ALLOWED, ERR_CHARGE_ALREADY_REVERSED,
)
from middleware import authorized
from response import success_object
from services.core import (
    new_record, touch, serialize_charge, wo_variance_posture,
    period_containing, current_open_period, resolve_overhead_rate,
    WO_CHARGEABLE_STATUSES,
)
from util import CLOCK, parse_date, dec, rhu_dec
from validate import (
    get_body, req_int, req_enum, req_date, require_path_resource, require_body_ref,
)
from routes.helpers import list_response, get_one

bp = Blueprint("cost_charges", __name__)


@bp.route("/ucp/cost-charges", methods=["POST"])
def create_charge():
    caller = authorized(["FieldClerk"])
    body = get_body()
    # Priority 3 — body FK existence.
    wo = require_body_ref(body, "work_order_id", "work_orders")
    # Priority 4 — shape.
    cost_type = req_enum(body, "cost_type", ["LABOR", "EQUIPMENT", "MATERIAL"])
    base_amount_cents = req_int(body, "base_amount_cents", positive=True)
    charge_date = req_date(body, "charge_date")
    d = parse_date(charge_date)
    # Priority 7 — state: SUSPENDED has its own error; only AUTHORIZED and
    # IN_PROGRESS accept charges (COMPLETED is frozen, everything else illegal).
    if wo["status"] == "SUSPENDED":
        raise_error(ERR_WORK_ORDER_SUSPENDED, "work order is SUSPENDED")
    if wo["status"] not in WO_CHARGEABLE_STATUSES:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    # Priority 9 — the charge date must fall in an existing period that is
    # currently OPEN or REOPENED.
    period = period_containing(d)
    if period is None:
        raise_error(ERR_PERIOD_NOT_FOUND, "charge_date falls inside no accounting period")
    if period["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_PERIOD_CLOSED, "charge_date falls in a CLOSED period")
    # Priority 10 — overhead rate resolution.
    schedule = resolve_overhead_rate(cost_type, wo["order_type"], d)
    if schedule is None:
        raise_error(ERR_OVERHEAD_RATE_NOT_FOUND, "no overhead schedule covers (cost_type, order_type, charge_date)")
    # Priority 11 — the variance hold blocks the NEXT charge; the charge that
    # itself crosses the threshold is allowed to post.
    if wo_variance_posture(wo["id"]) == "RE_ESTIMATE_REQUIRED":
        raise_error(ERR_VARIANCE_HOLD, "variance posture is RE_ESTIMATE_REQUIRED")

    # Per-row pinned rounding (PRD 2.5): overhead rounded per charge row FIRST.
    rate_pct = schedule["rate_pct"]
    overhead_amount_cents = rhu_dec(Decimal(base_amount_cents) * dec(rate_pct) / Decimal(100))
    rec = new_record()
    rec.update({
        "work_order_id": wo["id"],
        "cost_type": cost_type,
        "base_amount_cents": base_amount_cents,
        "charge_date": charge_date,
        "accounting_period_id": period["id"],
        "kind": "ORIGINAL",
        "reverses_charge_id": None,
        "overhead_rate_pct": rate_pct,
        "overhead_amount_cents": overhead_amount_cents,
        "total_cents": base_amount_cents + overhead_amount_cents,
        "status": "POSTED",
        "posted_by_user_id": caller.user_id,
    })
    db["cost_charges"][rec["id"]] = rec
    touch(wo)  # actual_direct_cents / cwip_cents / variance_posture recomputed
    return success_object(serialize_charge(rec), status=201)


@bp.route("/ucp/cost-charges/<charge_id>", methods=["GET"])
def get_charge(charge_id):
    return get_one("cost_charges", serialize_charge, charge_id)


@bp.route("/ucp/cost-charges", methods=["GET"])
def list_charges():
    filters = {
        "work_order_id": request.args.get("work_order_id"),
        "accounting_period_id": request.args.get("accounting_period_id"),
        "cost_type": request.args.get("cost_type"),
        "kind": request.args.get("kind"),
        "reverses_charge_id": request.args.get("reverses_charge_id"),
    }
    return list_response("cost_charges", serialize_charge, filters)


@bp.route("/ucp/cost-charges/<charge_id>/reverse", methods=["POST"])
def reverse_charge(charge_id):
    caller = authorized(["FieldClerk"])
    charge = require_path_resource("cost_charges", charge_id)
    # Priority 7 — only a POSTED ORIGINAL may be reversed.
    if charge["kind"] == "REVERSAL":
        raise_error(ERR_REVERSAL_NOT_ALLOWED, "REVERSAL rows can never be reversed")
    if charge["status"] == "REVERSED":
        raise_error(ERR_CHARGE_ALREADY_REVERSED, "charge is already REVERSED")
    # Priority 9 — an OPEN or REOPENED period must exist to receive the
    # reversal row (prior-period adjustment).
    period = current_open_period()
    if period is None:
        raise_error(ERR_PERIOD_NOT_FOUND, "no OPEN or REOPENED period exists for the reversal")

    rec = new_record()
    rec.update({
        "work_order_id": charge["work_order_id"],
        "cost_type": charge["cost_type"],
        "base_amount_cents": -charge["base_amount_cents"],
        "charge_date": CLOCK.today().isoformat(),  # informational logical-clock date
        "accounting_period_id": period["id"],
        "kind": "REVERSAL",
        "reverses_charge_id": charge["id"],
        "overhead_rate_pct": charge["overhead_rate_pct"],
        "overhead_amount_cents": -charge["overhead_amount_cents"],
        "total_cents": -charge["total_cents"],
        "status": "POSTED",
        "posted_by_user_id": caller.user_id,
    })
    db["cost_charges"][rec["id"]] = rec
    charge["status"] = "REVERSED"
    touch(charge)
    # The pair nets to zero: balances and variance posture recompute.
    touch(db["work_orders"][charge["work_order_id"]])
    return success_object(serialize_charge(rec), status=201)
