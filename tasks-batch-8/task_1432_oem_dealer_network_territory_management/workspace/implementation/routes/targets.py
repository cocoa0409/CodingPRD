"""SalesTarget endpoints: create, list/get, close (final discount reckoning)."""

from __future__ import annotations

from decimal import Decimal
from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEALER_NOT_FOUND,
    ERR_TARGET_NOT_FOUND,
    ERR_DUPLICATE_TARGET,
    ERR_TARGET_NOT_OPEN,
    ERR_QUARTER_NOT_ENDED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import (
    find_target,
    first_day_of_following_quarter,
    quarter_of,
    tier_name_for_ratio,
    tier_rate_for_ratio,
)
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    round_half_up_int,
    sort_by_created_at,
)

bp = Blueprint("targets", __name__)


def get_target_or_404(target_id: str) -> dict:
    target = db.targets.get(target_id)
    if target is None:
        raise_err(ERR_TARGET_NOT_FOUND, "Sales target id does not exist")
    return target


@bp.route("/sales-targets", methods=["POST"])
@require_roles("OemSalesOps")
def create_target(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    period_year = require_int(body, "period_year")
    period_quarter = require_int(body, "period_quarter")
    if period_quarter < 1 or period_quarter > 4:
        raise_err(ERR_INVALID_REQUEST, "period_quarter must be in 1..4")
    target_units = require_int(body, "target_units")
    if target_units <= 0:
        raise_err(ERR_INVALID_REQUEST, "target_units must be > 0")

    # Priority 4 existence: body-referenced dealer.
    if dealer_id not in db.dealers:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 8: one target per (dealer, year, quarter).
    if find_target(dealer_id, period_year, period_quarter) is not None:
        raise_err(ERR_DUPLICATE_TARGET, "Target already exists for (dealer_id, period_year, period_quarter)")

    target = {
        "dealer_id": dealer_id,
        "period_year": period_year,
        "period_quarter": period_quarter,
        "target_units": target_units,
        "achieved_units": 0,
        "final_discount_rate": None,
        "status": "OPEN",
    }
    db.stamp_new(target)
    db.targets[target["id"]] = target
    return success_object(serialize(target), 201)


@bp.route("/sales-targets", methods=["GET"])
@require_roles("Any")
def list_targets(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.targets.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/sales-targets/<target_id>", methods=["GET"])
@require_roles("Any")
def get_target(target_id: str, _user_id: str, _role: str):
    target = get_target_or_404(target_id)
    return success_object(serialize(target))


@bp.route("/sales-targets/<target_id>/close", methods=["POST"])
@require_roles("OemSalesOps")
def close_target(target_id: str, _user_id: str, _role: str):
    target = get_target_or_404(target_id)

    # Priority 6 state.
    if target["status"] != "OPEN":
        raise_err(ERR_TARGET_NOT_OPEN, "Close requires target OPEN")

    # Priority 9 temporal: current logical date >= first day of the following quarter.
    boundary = first_day_of_following_quarter(target["period_year"], target["period_quarter"])
    if db.clock_date() < boundary:
        raise_err(
            ERR_QUARTER_NOT_ENDED,
            "Close requires current logical date >= first day of the following quarter",
        )

    dealer = db.dealers.get(target["dealer_id"])

    # FINAL variant of tier_discount: counted units = achieved_units.
    ratio = Decimal(target["achieved_units"]) / Decimal(target["target_units"])
    rate = tier_rate_for_ratio(ratio)
    target["final_discount_rate"] = float(rate)
    target["status"] = (
        "CLOSED_MET" if target["achieved_units"] >= target["target_units"] else "CLOSED_MISSED"
    )
    db.touch(target)

    # Every ACCEPTED sale in the quarter gets its final discount; the deltas
    # accumulate into the dealer's discount reconciliation.
    reconciliation_delta = 0
    for sale in db.unit_sales.values():
        if sale["dealer_id"] != target["dealer_id"] or sale["status"] != "ACCEPTED":
            continue
        if quarter_of(sale["sale_date"]) != (target["period_year"], target["period_quarter"]):
            continue
        final = round_half_up_int(Decimal(sale["list_price_cents"]) * rate)
        sale["final_discount_cents"] = final
        reconciliation_delta += final - sale["provisional_discount_cents"]
        db.touch(sale)

    if dealer is not None:
        dealer["discount_reconciliation_cents"] += reconciliation_delta
        dealer["tier"] = tier_name_for_ratio(ratio)
        db.touch(dealer)

    return success_object(serialize(target))
