"""CollarTrueUp endpoints (PRD §3.9)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import db
import util
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("collar_true_ups", __name__)

READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner", "ManagingPartner")


@bp.post("/firms/<firmId>/matters/<matterId>/run_year_end_collar_true_up")
def run_true_up(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    firm = util.get_firm(firmId)
    matter = util.get_matter_scoped(firmId, matterId)

    # Resolve the arrangement to true up: the matter's current ACTIVE one,
    # else the latest SUPERSEDED one.
    arrangement = None
    if matter.get("fee_arrangement_id"):
        arrangement = db.fee_arrangements.get(matter["fee_arrangement_id"])
    if arrangement is None or arrangement.get("status") != "ACTIVE":
        active = [a for a in derived.arrangements_of(matterId) if a.get("status") == "ACTIVE"]
        if active:
            arrangement = active[0]
    if arrangement is None:
        superseded = [a for a in derived.arrangements_of(matterId) if a.get("status") == "SUPERSEDED"]
        if superseded:
            arrangement = max(superseded, key=util.order_key)

    if arrangement is None or arrangement.get("arrangement_type") != "COLLAR":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Year-end true-up requires a COLLAR arrangement", 409)

    if not util.fiscal_year_ended(firm, int(arrangement.get("fiscal_year_index", 0))):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Fiscal year has not yet ended for the arrangement", 409)

    year = int(arrangement["fiscal_year_index"])
    actual_year_fees = sum(
        int(e.get("billable_amount_cents", 0))
        for e in derived.entries_of(matterId)
        if e.get("status") == "BILLED"
        and e.get("period_index") is not None
        and util.fiscal_year_for_period(firm, int(e["period_index"])) == year
    )

    lb = int(arrangement.get("collar_lower_bound_cents", 0))
    ub = int(arrangement.get("collar_upper_bound_cents", 0))
    share = int(arrangement.get("collar_share_pct_bp", 0))

    if actual_year_fees < lb:
        shortfall = lb - actual_year_fees
        amount = int((Decimal(share) * Decimal(shortfall) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        true_up_amount = -amount
        direction = "COLLECT_FROM_CLIENT"
    elif actual_year_fees > ub:
        excess = actual_year_fees - ub
        amount = int((Decimal(share) * Decimal(excess) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        true_up_amount = amount
        direction = "REBATE_TO_CLIENT"
    else:
        true_up_amount = 0
        direction = "IN_BAND"

    tu = util.new_resource()
    tu.update({
        "matter_id": matterId,
        "firm_id": firmId,
        "fee_arrangement_id": arrangement["id"],
        "fiscal_year_index": year,
        "actual_year_fees_cents": actual_year_fees,
        "true_up_amount_cents": true_up_amount,
        "direction": direction,
        "status": "COMPUTED",
    })
    db.collar_true_ups[tu["id"]] = tu
    return success_object(tu, 201)


@bp.get("/firms/collar_true_ups/<trueUpId>")
def get_true_up(trueUpId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    tu = util.get_true_up_flat(trueUpId)
    return success_object(tu, 200)


@bp.get("/firms/collar_true_ups")
def list_true_ups():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters(["firm_id", "matter_id", "fee_arrangement_id", "status"])
    items = util.apply_filters(list(db.collar_true_ups.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/collar_true_ups")
def list_true_ups_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status"])
    items = [t for t in db.collar_true_ups.values() if t.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/collar_true_ups/<trueUpId>/settle")
def settle_true_up(firmId, trueUpId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    tu = util.get_true_up_scoped(firmId, trueUpId)
    if tu["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a COMPUTED true-up can be settled", 409)
    tu["status"] = "SETTLED"
    util.touch(tu)
    return success_object(tu, 200)


@bp.post("/firms/<firmId>/collar_true_ups/<trueUpId>/waive")
def waive_true_up(firmId, trueUpId):
    ctx = get_context()
    require_roles(ctx, "ManagingPartner")
    tu = util.get_true_up_scoped(firmId, trueUpId)
    if tu["status"] != "COMPUTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a COMPUTED true-up can be waived", 409)
    tu["status"] = "WAIVED"
    util.touch(tu)
    return success_object(tu, 200)
