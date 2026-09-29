"""Dealer accounts and floor-plan credit administration (PRD 3.8)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import db, new_id, public, stamp_new, touch
from middleware import actor, endpoint, is_dealer
from response import created, ok
from services import rollups

bp = Blueprint("dealers", __name__)

ADJUSTMENTS = ("LIMIT_INCREASE", "LIMIT_DECREASE", "PAYOFF", "CREDIT_HOLD", "CREDIT_RELEASE")


@bp.route("/dealers", methods=["POST"])
@endpoint(["SalesAdmin"])
def create_dealer():
    data = v.body()
    dealer_code = v.req_code(data, "dealer_code", 4, 16)
    name = v.req_str(data, "name")
    labor_rate = v.req_int(data, "labor_rate_cents_per_hour", 1)
    limit_cents = v.opt_int(data, "floor_plan_limit_cents", 0, 0)
    quota = v.req_int(data, "allocation_quota_per_month", 0)

    lookups.unique_or_409(db.dealers, "dealer_code", dealer_code)

    row = {
        "id": new_id(),
        "dealer_code": dealer_code,
        "name": name,
        "labor_rate_cents_per_hour": labor_rate,
        "floor_plan_limit_cents": limit_cents,
        "floor_plan_outstanding_cents": 0,
        "floor_plan_available_cents": limit_cents,
        "allocation_quota_per_month": quota,
        "allocations_current_month_count": 0,
        "allocations_ytd_count": 0,
        "warranty_receivable_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(row)
    db.dealers[row["id"]] = row
    return created(public(row))


@bp.route("/dealers/<dealer_id>", methods=["GET"])
@endpoint(["SalesAdmin", "PlantEngineer", "Dealer"])
def get_dealer(dealer_id):
    if is_dealer() and dealer_id != actor():
        raise errors.dealer_scope(actor(), dealer_id)
    return ok(public(lookups.dealer_or_404(dealer_id)))


@bp.route("/dealers/<dealer_id>/floor-plan-adjustments", methods=["POST"])
@endpoint(["SalesAdmin"])
def adjust_floor_plan(dealer_id):
    dealer = lookups.dealer_or_404(dealer_id)
    data = v.body()

    # ladder step 5: body foreign keys resolve before the schema is judged
    order = None
    order_id = v.opt_id(data, "order_id")
    if order_id is not None:
        order = lookups.order_or_404(order_id)

    adjustment_type = v.req_enum(data, "adjustment_type", ADJUSTMENTS)
    amount_cents = v.req_int(data, "amount_cents", 0)
    if v.present(data, "note"):
        v.req_str(data, "note")

    if adjustment_type == "LIMIT_INCREASE":
        dealer["floor_plan_limit_cents"] = dealer["floor_plan_limit_cents"] + amount_cents
    elif adjustment_type == "LIMIT_DECREASE":
        dealer["floor_plan_limit_cents"] = dealer["floor_plan_limit_cents"] - amount_cents
    elif adjustment_type == "PAYOFF":
        if order is None:
            raise errors.invalid("order_id is required for a PAYOFF adjustment")
        if order["dealer_id"] != dealer["id"]:
            raise errors.invalid("order_id does not belong to this dealer")
        if order["floor_plan_status"] != "DRAWN":
            raise errors.invalid("order_id does not carry a DRAWN floor plan draw")
        order["floor_plan_status"] = "REPAID"
        touch(order)
    elif adjustment_type == "CREDIT_HOLD":
        dealer["status"] = "CREDIT_HOLD"
    else:
        dealer["status"] = "ACTIVE"

    rollups.recompute_dealer(dealer)
    if adjustment_type == "LIMIT_DECREASE" and \
            dealer["floor_plan_outstanding_cents"] > dealer["floor_plan_limit_cents"]:
        dealer["status"] = "CREDIT_HOLD"
    return ok(public(dealer))
