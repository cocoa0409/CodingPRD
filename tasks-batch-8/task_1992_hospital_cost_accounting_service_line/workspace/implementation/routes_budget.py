"""Budget period routes (PRD §3.5): creation, live flex recompute, lock."""

from flask import Blueprint, request

import errors
import serialize
from calc import (budget_period_actual_volume, flex_tier_rate, r2,
                  recompute_budget_period)
from db import new_common_fields, store, touch
from helpers import (auth, check_period_format, check_unknown_fields,
                     get_body, get_number, get_period, get_str, paginate)
from response import success

bp = Blueprint("budget", __name__)

READ_ROLES = ("FinanceController", "CostAnalyst", "ServiceLineManager")
FC = ("FinanceController",)

CONSTRAINTS_NOTE = "Unique (cost_center_id, period) pair"


def _sorted(table):
    return sorted(table.values(), key=lambda e: e["_seq"])


def _get_bp_or_404(rid):
    bp = store.budget_periods.get(rid)
    if bp is None:
        errors.not_found("BudgetPeriod")
    return bp


@bp.route("/cost-accounting/budget-periods", methods=["POST"])
def create_budget_period():
    auth(*FC)
    body = get_body()
    # Family 3: body FK existence in declared input order.
    cc = None
    if body.get("cost_center_id") is not None:
        cc = store.cost_centers.get(body["cost_center_id"])
        if cc is None:
            errors.not_found("CostCenter")
    # The budgeted pool must be an OVERHEAD center.
    if cc is not None and cc["cost_type"] != "OVERHEAD":
        errors.invalid_request(
            "cost_center_id must reference an OVERHEAD cost center")
    # Family 9: temporal windowing — period format, then pair uniqueness.
    check_period_format(body.get("period"), "period")
    if cc is not None and body.get("period") is not None:
        for other in store.budget_periods.values():
            if (other["cost_center_id"] == cc["id"]
                    and other["period"] == body["period"]):
                errors.duplicate_budget_period()
    # Family 10: request sanity.
    check_unknown_fields(body, ["cost_center_id", "period", "static_budget_amount"])
    get_str(body, "cost_center_id")
    period = get_period(body, "period")
    static_budget_amount = get_number(body, "static_budget_amount", gt=0)
    bp = {
        **new_common_fields(),
        "_seq": store.next_seq(),
        "cost_center_id": cc["id"],
        "period": period,
        "static_budget_amount": static_budget_amount,
        "status": "OPEN",
        "constraints_note": CONSTRAINTS_NOTE,
    }
    # Initialize flex/variance against current actuals (0 at creation).
    volume = budget_period_actual_volume(bp)
    flexed = r2(flex_tier_rate(volume) * volume)
    variance = r2(flexed - static_budget_amount)
    bp["actual_indirect_volume"] = volume
    bp["flexed_overhead"] = flexed
    bp["variance_amount"] = variance
    bp["variance_direction"] = ("FAVORABLE" if variance < 0
                                else "ON_BUDGET" if variance == 0
                                else "UNFAVORABLE")
    store.budget_periods[bp["id"]] = bp
    return success(serialize.budget_period(bp), code=201)


@bp.route("/cost-accounting/budget-periods", methods=["GET"])
def list_budget_periods():
    auth(*READ_ROLES)
    items = _sorted(store.budget_periods)
    for param in ("cost_center_id", "period", "status"):
        value = request.args.get(param)
        if value:
            items = [b for b in items if b.get(param) == value]
    for bp in items:
        recompute_budget_period(bp)  # live recompute while OPEN
    page, meta = paginate(items)
    return success([serialize.budget_period(b) for b in page],
                   response_type="array", pagination=meta)


@bp.route("/cost-accounting/budget-periods/<rid>", methods=["GET"])
def get_budget_period(rid):
    auth(*READ_ROLES)
    bp = _get_bp_or_404(rid)
    recompute_budget_period(bp)  # live recompute while OPEN
    return success(serialize.budget_period(bp))


@bp.route("/cost-accounting/budget-periods/<rid>/lock", methods=["POST"])
def lock_budget_period(rid):
    auth(*FC)
    bp = _get_bp_or_404(rid)
    body = get_body()
    check_unknown_fields(body, [])
    if bp["status"] != "OPEN":
        errors.invalid_state("BudgetPeriod is not OPEN")
    # Family 8: refuse while any POSTED case of this period+pool is priced
    # under a stale model version.
    for c in store.cases.values():
        if c["status"] != "POSTED" or c["period"] != bp["period"]:
            continue
        model = store.cost_models.get(c["cost_model_id"])
        if model is None or model["overhead_cost_center_id"] != bp["cost_center_id"]:
            continue
        if c["version_at_post"] != model["version"]:
            errors.period_has_stale_cases()
    # Freeze the final flex position, then lock every POSTED case of the
    # period priced by a model using this pool.
    recompute_budget_period(bp)
    for c in store.cases.values():
        if c["status"] != "POSTED" or c["period"] != bp["period"]:
            continue
        model = store.cost_models.get(c["cost_model_id"])
        if model is None or model["overhead_cost_center_id"] != bp["cost_center_id"]:
            continue
        c["status"] = "LOCKED"
        touch(c)
    bp["status"] = "LOCKED"
    touch(bp)
    return success(serialize.budget_period(bp))
