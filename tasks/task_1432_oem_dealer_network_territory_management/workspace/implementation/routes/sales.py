"""UnitSale endpoints: report (provisional discount), decide (accept/reject
with floor-plan payoff cascade), void (payoff-lock)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEALER_NOT_FOUND,
    ERR_SALE_NOT_FOUND,
    ERR_DEALER_IDENTITY_MISMATCH,
    ERR_TARGET_NOT_OPEN,
    ERR_DUPLICATE_UNIT_SERIAL,
    ERR_SALE_NOT_REPORTED,
    ERR_SALE_NOT_ACCEPTED,
    ERR_SALE_PAYOFF_LOCKED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import find_target, provisional_discount_cents, quarter_of
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("unit_sales", __name__)


def get_sale_or_404(sale_id: str) -> dict:
    sale = db.unit_sales.get(sale_id)
    if sale is None:
        raise_err(ERR_SALE_NOT_FOUND, "Unit sale id does not exist")
    return sale


@bp.route("/unit-sales", methods=["POST"])
@require_roles("DealerUser")
def create_sale(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    unit_serial = require_string(body, "unit_serial")
    sale_date = require_date(body, "sale_date")
    list_price_cents = require_int(body, "list_price_cents")
    if list_price_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "list_price_cents must be > 0")

    # Priority 4 existence.
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 5 ownership: DealerUser may only report for their own dealership.
    if dealer_id != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "DealerUser body dealer_id != X-User-ID")

    # Priority 6 state: an OPEN target must exist for the sale's quarter.
    year, quarter = quarter_of(sale_date)
    target = find_target(dealer_id, year, quarter)
    if target is None or target["status"] != "OPEN":
        raise_err(ERR_TARGET_NOT_OPEN, "Target missing or not OPEN for the sale's quarter")

    # Priority 8: serial unique per dealer among non-REJECTED/non-VOIDED sales.
    for s in db.unit_sales.values():
        if (
            s["dealer_id"] == dealer_id
            and s["unit_serial"] == unit_serial
            and s["status"] not in ("REJECTED", "VOIDED")
        ):
            raise_err(ERR_DUPLICATE_UNIT_SERIAL, "Non-terminal sale with same (dealer_id, unit_serial) exists")

    sale = {
        "dealer_id": dealer_id,
        "unit_serial": unit_serial,
        "sale_date": sale_date,
        "list_price_cents": list_price_cents,
        "provisional_discount_cents": provisional_discount_cents(
            list_price_cents, target["achieved_units"], target["target_units"]
        ),
        "final_discount_cents": None,
        "status": "REPORTED",
    }
    db.stamp_new(sale)
    db.unit_sales[sale["id"]] = sale
    return success_object(serialize(sale), 201)


@bp.route("/unit-sales", methods=["GET"])
@require_roles("Any")
def list_sales(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.unit_sales.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/unit-sales/<sale_id>", methods=["GET"])
@require_roles("Any")
def get_sale(sale_id: str, _user_id: str, _role: str):
    sale = get_sale_or_404(sale_id)
    return success_object(serialize(sale))


@bp.route("/unit-sales/<sale_id>/decide", methods=["POST"])
@require_roles("OemSalesOps")
def decide_sale(sale_id: str, _user_id: str, _role: str):
    body = get_json_body()
    decision = require_enum(body, "decision", {"ACCEPT", "REJECT"})
    sale = get_sale_or_404(sale_id)

    # Priority 6 state.
    if sale["status"] != "REPORTED":
        raise_err(ERR_SALE_NOT_REPORTED, "decide requires sale REPORTED")

    if decision == "REJECT":
        sale["status"] = "REJECTED"
        db.touch(sale)
        return success_object(serialize(sale))

    # ACCEPT also requires the quarter's target to exist and be OPEN.
    year, quarter = quarter_of(sale["sale_date"])
    target = find_target(sale["dealer_id"], year, quarter)
    if target is None or target["status"] != "OPEN":
        raise_err(ERR_TARGET_NOT_OPEN, "Target missing or not OPEN for the sale's quarter")

    sale["status"] = "ACCEPTED"
    db.touch(sale)
    target["achieved_units"] += 1
    db.touch(target)

    # Retail-sale payoff cascade: a live floor-plan advance on the same
    # (dealer, unit_serial) is paid off in full.
    dealer = db.dealers.get(sale["dealer_id"])
    for adv in db.advances.values():
        if (
            adv["dealer_id"] == sale["dealer_id"]
            and adv["unit_serial"] == sale["unit_serial"]
            and adv["status"] in ("OPEN", "CURTAILED", "PAST_DUE")
        ):
            remaining = adv["advance_cents"] - adv["paid_curtailments_cents"]
            adv["paid_curtailments_cents"] = adv["advance_cents"]
            adv["status"] = "PAID_OFF"
            adv["_paid_off_by_sale_id"] = sale["id"]
            db.touch(adv)
            if dealer is not None:
                dealer["floorplan_utilization_cents"] -= remaining
    if dealer is not None and any(
        a.get("_paid_off_by_sale_id") == sale["id"] for a in db.advances.values()
    ):
        db.touch(dealer)
    return success_object(serialize(sale))


@bp.route("/unit-sales/<sale_id>/void", methods=["POST"])
@require_roles("OemSalesOps")
def void_sale(sale_id: str, _user_id: str, _role: str):
    sale = get_sale_or_404(sale_id)

    # Priority 6 state.
    if sale["status"] != "ACCEPTED":
        raise_err(ERR_SALE_NOT_ACCEPTED, "void requires sale ACCEPTED")

    # Priority 10 referential: void blocked when this sale's acceptance paid
    # off the linked floor-plan advance.
    for adv in db.advances.values():
        if (
            adv["dealer_id"] == sale["dealer_id"]
            and adv["unit_serial"] == sale["unit_serial"]
            and adv["status"] == "PAID_OFF"
            and adv.get("_paid_off_by_sale_id") == sale["id"]
        ):
            raise_err(
                ERR_SALE_PAYOFF_LOCKED,
                "Void blocked: linked floor-plan advance was paid off by this sale's acceptance",
            )

    sale["status"] = "VOIDED"
    db.touch(sale)
    year, quarter = quarter_of(sale["sale_date"])
    target = find_target(sale["dealer_id"], year, quarter)
    if target is not None:
        target["achieved_units"] -= 1
        db.touch(target)
    return success_object(serialize(sale))
