"""NAV period lifecycle: finalize (gross return, mgmt fee accrual, series
equalization) and close (redemption settlement with gate proration, performance
fee crystallization, statement generation, series roll, next period open)."""
from datetime import timedelta
from decimal import Decimal

from db import db
from services.core import (
    touch, stamp_new, class_nav_per_share, reset_period_accumulators,
    get_share_class,
)
from util import (
    parse_datetime, dec, quantize_half_up, round_half_up_int, add_calendar_months,
)


def _days_in_period(period) -> int:
    start = parse_datetime(period["period_start_utc"])
    end = parse_datetime(period["period_end_utc"])
    return max(0, (end - start).days)


def compute_equalization_factor_bps(opening_nav_cents, closing_nav: Decimal,
                                    hurdle_rate_bps, performance_fee_bps,
                                    days_in_period) -> int:
    """series_equalization_factor: full precision until one final round-half-up."""
    O = dec(opening_nav_cents)
    gross_return = (closing_nav - O) / O
    hurdle_return = (dec(hurdle_rate_bps) / Decimal(10000)) * (dec(days_in_period) / Decimal(365))
    if gross_return <= hurdle_return:
        return 0
    excess_return = gross_return - hurdle_return
    incentive = excess_return * (dec(performance_fee_bps) / Decimal(10000))
    return int(quantize_half_up(incentive * Decimal(10000)))


def finalize_period(fund, period, gross_return_bps):
    g = dec(gross_return_bps) / Decimal(10000)
    days = _days_in_period(period)

    # Per share class: evolve NAV per share by the fund-level gross return.
    class_closing_nav = {}
    for sc in db["share_classes"].values():
        if sc["fund_id"] != fund["id"]:
            continue
        opening = class_nav_per_share(sc)
        closing = opening * (Decimal(1) + g)
        sc["_nav_per_share"] = closing
        class_closing_nav[sc["id"]] = closing

    # Per capital account: apply gross return, accrue management fee
    # (accrued for reporting; not deducted from the marked-to-market balance),
    # refresh the high-water mark.
    for account in db["capital_accounts"].values():
        sc = db["share_classes"].get(account["share_class_id"])
        if sc is None or sc["fund_id"] != fund["id"] or account["status"] == "CLOSED":
            continue
        new_balance = round_half_up_int(
            account["current_balance_cents"] * (10000 + gross_return_bps), 10000)
        account["current_balance_cents"] = new_balance
        mgmt_fee = round_half_up_int(
            new_balance * sc["management_fee_bps"] * days, 10000 * 365)
        account["_period_mgmt_fee"] = account.get("_period_mgmt_fee", 0) + mgmt_fee
        if new_balance > account["high_water_mark_cents"]:
            account["high_water_mark_cents"] = new_balance
        touch(account)
        for lot in db["series_lots"].values():
            if lot["capital_account_id"] == account["id"] and lot["status"] in (
                    "OUTSTANDING", "PARTIALLY_REDEEMED"):
                lot["current_value_cents"] = round_half_up_int(
                    lot["current_value_cents"] * (10000 + gross_return_bps), 10000)
                touch(lot)

    # Per OPEN series of the fund's classes: compute + lock equalization factor.
    for series in db["series"].values():
        sc = db["share_classes"].get(series["share_class_id"])
        if sc is None or sc["fund_id"] != fund["id"] or series["status"] != "OPEN":
            continue
        closing_nav = class_closing_nav.get(sc["id"], class_nav_per_share(sc))
        series["equalization_factor_bps"] = compute_equalization_factor_bps(
            series["opening_nav_per_share_cents"], closing_nav,
            sc["hurdle_rate_bps"], sc["performance_fee_bps"], days)
        series["status"] = "FINALIZED"
        touch(series)

    # Fund net assets track the sum of marked-to-market balances.
    total = 0
    for account in db["capital_accounts"].values():
        sc = db["share_classes"].get(account["share_class_id"])
        if sc is not None and sc["fund_id"] == fund["id"] and account["status"] != "CLOSED":
            total += account["current_balance_cents"]
    fund["total_net_assets_cents"] = total

    period["gross_return_bps"] = gross_return_bps
    period["status"] = "NAV_FINALIZED"
    touch(period)
    touch(fund)


# ---------------------------------------------------------------------------
# Gate proration (calculation redemption_gate_proration, PRD 3.7)
# ---------------------------------------------------------------------------


def apply_gate_and_settlements(fund, period, approved):
    """Settle APPROVED requests for the closing period. Returns per-request
    list of (request, settled_cents, gated_bool)."""
    total_approved = sum(r["requested_amount_cents"] for r in approved)
    gate_pool = int((dec(fund["gate_threshold_pct"]) * fund["total_net_assets_cents"])
                    .to_integral_value(rounding="ROUND_FLOOR"))
    gated = total_approved > gate_pool

    if not gated:
        for r in approved:
            r["gate_applied_pct"] = 0
        return [(r, r["requested_amount_cents"], False) for r in approved]

    gate_applied_pct = float(quantize_half_up(
        Decimal(1) - dec(gate_pool) / dec(total_approved), 6))

    floors = []
    remainders = []
    for r in approved:
        req = r["requested_amount_cents"]
        settled_floor = (req * gate_pool) // total_approved
        remainder = req * gate_pool - settled_floor * total_approved
        floors.append(settled_floor)
        remainders.append(remainder)

    leftover = gate_pool - sum(floors)
    # Largest-remainder distribution; ties: requested DESC, notice ASC,
    # capital account created_at ASC.
    order = sorted(
        range(len(approved)),
        key=lambda i: (
            -remainders[i],
            -approved[i]["requested_amount_cents"],
            approved[i]["notice_given_at_utc"],
            db["capital_accounts"][approved[i]["capital_account_id"]]["created_at"],
        ),
    )
    for i in order[:leftover]:
        floors[i] += 1

    result = []
    for i, r in enumerate(approved):
        r["gate_applied_pct"] = gate_applied_pct
        r["status"] = "PARTIALLY_APPROVED"
        result.append((r, floors[i], True))
    return result


def _settle_one(fund, period, request, settled_amount, new_period=None):
    account = db["capital_accounts"][request["capital_account_id"]]
    request["settled_amount_cents"] = settled_amount
    request["effective_period_id"] = period["id"]
    request["status"] = "SETTLED"
    touch(request)

    account["current_balance_cents"] -= settled_amount
    account["_period_distributions"] = account.get("_period_distributions", 0) + settled_amount
    fund["total_net_assets_cents"] -= settled_amount

    # FIFO lot consumption.
    remaining = settled_amount
    lots = [l for l in db["series_lots"].values()
            if l["capital_account_id"] == account["id"]
            and l["status"] in ("OUTSTANDING", "PARTIALLY_REDEEMED")]
    lots.sort(key=lambda l: (l["created_at"], l["_seq"]))
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["current_value_cents"], remaining)
        lot["current_value_cents"] -= take
        remaining -= take
        lot["status"] = "FULLY_REDEEMED" if lot["current_value_cents"] <= 0 else "PARTIALLY_REDEEMED"
        touch(lot)

    if account["current_balance_cents"] <= 0:
        account["current_balance_cents"] = max(0, account["current_balance_cents"])
        account["status"] = "CLOSED"
    else:
        account["status"] = "ACTIVE"
    touch(account)

    # Deferred remainder spawns a fresh PENDING request for the next period,
    # preserving the original notice date.
    deferred = request["requested_amount_cents"] - settled_amount
    if deferred > 0 and new_period is not None:
        new_req = stamp_new({
            "capital_account_id": request["capital_account_id"],
            "investor_id": request["investor_id"],
            "requested_amount_cents": deferred,
            "requested_shares": None,
            "notice_given_at_utc": request["notice_given_at_utc"],
            "requested_effective_period_id": new_period["id"],
            "effective_period_id": new_period["id"],
            "gate_applied_pct": 0,
            "settled_amount_cents": 0,
            "status": "PENDING",
            "_fund_id": fund["id"],
            "_rejection_reason": None,
        })
        db["redemptions"][new_req["id"]] = new_req


def _crystallize_performance_fee(account, share_class):
    perf_bps = share_class["performance_fee_bps"]
    if perf_bps <= 0:
        return
    if share_class["high_water_mark_required"]:
        gain = max(0, account["current_balance_cents"] - account["high_water_mark_cents"])
    else:
        # Gain over net invested capital this period (opening + contributions
        # - distributions); without HWM any positive period gain is fee-bearing.
        net_invested = (account.get("_period_opening", 0)
                        + account.get("_period_contributions", 0)
                        - account.get("_period_distributions", 0))
        gain = max(0, account["current_balance_cents"] - net_invested)
    if gain <= 0:
        return
    fee = round_half_up_int(gain * perf_bps, 10000)
    account["accrued_performance_fee_cents"] += fee
    account["_period_perf_fee"] = account.get("_period_perf_fee", 0) + fee
    if account["current_balance_cents"] > account["high_water_mark_cents"]:
        account["high_water_mark_cents"] = account["current_balance_cents"]
    touch(account)


def _roll_finalized_zero_factor_series(fund):
    for sc in db["share_classes"].values():
        if sc["fund_id"] != fund["id"]:
            continue
        lead = None
        for s in db["series"].values():
            if s["share_class_id"] == sc["id"] and s["series_index"] == 1:
                lead = s
                break
        if lead is None:
            continue
        for series in db["series"].values():
            if (series["share_class_id"] == sc["id"] and series["status"] == "FINALIZED"
                    and series["equalization_factor_bps"] == 0
                    and series["series_index"] != 1):
                series["status"] = "ROLLED"
                touch(series)
                for lot in list(db["series_lots"].values()):
                    if lot["series_id"] == series["id"] and lot["status"] == "OUTSTANDING":
                        lot["status"] = "ROLLED"
                        touch(lot)
                        new_lot = stamp_new({
                            "capital_account_id": lot["capital_account_id"],
                            "series_id": lead["id"],
                            "nav_period_id": fund["current_nav_period_id"],
                            "shares": lot["shares"],
                            "cost_basis_cents": lot["cost_basis_cents"],
                            "current_value_cents": lot["current_value_cents"],
                            "equalization_credit_cents": lot["equalization_credit_cents"],
                            "status": "OUTSTANDING",
                        })
                        db["series_lots"][new_lot["id"]] = new_lot


def close_period(fund, period):
    now = __import__("util").CLOCK.now()

    # 1. Settle approved redemptions for this period (gate if binds).
    approved = [r for r in db["redemptions"].values()
                if r.get("_fund_id") == fund["id"] and r["status"] == "APPROVED"
                and r["effective_period_id"] == period["id"]]
    approved.sort(key=lambda r: (r["created_at"], r["_seq"]))

    # Auto-open the successor period first so deferred requests can target it.
    old_end = parse_datetime(period["period_end_utc"])
    new_index = period["period_index"] + 1
    new_period = stamp_new({
        "fund_id": fund["id"],
        "period_index": new_index,
        "period_start_utc": period["period_end_utc"],
        "period_end_utc": __import__("util").fmt_datetime(add_calendar_months(old_end, 1)),
        "gross_return_bps": None,
        "status": "OPEN",
    })

    settlements = apply_gate_and_settlements(fund, period, approved)
    for request, settled_amount, _gated in settlements:
        _settle_one(fund, period, request, settled_amount, new_period=new_period)

    # 2. Crystallize performance fees; 3. generate statements per active account.
    for account in db["capital_accounts"].values():
        sc = db["share_classes"].get(account["share_class_id"])
        if sc is None or sc["fund_id"] != fund["id"]:
            continue
        if account["status"] not in ("ACTIVE", "REDEMPTION_PENDING", "CLOSED"):
            continue
        had_activity = (account["status"] != "CLOSED")
        if account["status"] != "CLOSED":
            _crystallize_performance_fee(account, sc)
        statement = stamp_new({
            "capital_account_id": account["id"],
            "nav_period_id": period["id"],
            "opening_balance_cents": account.get("_period_opening", 0),
            "closing_balance_cents": account["current_balance_cents"],
            "contributions_cents": account.get("_period_contributions", 0),
            "distributions_cents": account.get("_period_distributions", 0),
            "management_fee_cents": account.get("_period_mgmt_fee", 0),
            "performance_fee_cents": account.get("_period_perf_fee", 0),
            "delivered_at_utc": None,
            "status": "FINALIZED",
        })
        db["statements"][statement["id"]] = statement
        reset_period_accumulators(account, account["current_balance_cents"])

    # 4. Roll FINALIZED zero-factor series into the lead series.
    _roll_finalized_zero_factor_series(fund)

    # 5. Close the period, open the successor, bump fund version.
    period["status"] = "CLOSED"
    touch(period)
    db["nav_periods"][new_period["id"]] = new_period
    fund["current_nav_period_id"] = new_period["id"]
    touch(fund)
    return new_period


def open_period(fund, period_end_iso):
    """POST /funds/{id}/nav-periods: open a period starting at the logical clock."""
    from util import CLOCK
    idx = sum(1 for p in db["nav_periods"].values() if p["fund_id"] == fund["id"]) + 1
    period = stamp_new({
        "fund_id": fund["id"],
        "period_index": idx,
        "period_start_utc": CLOCK.now_iso(),
        "period_end_utc": period_end_iso,
        "gross_return_bps": None,
        "status": "OPEN",
    })
    db["nav_periods"][period["id"]] = period
    fund["current_nav_period_id"] = period["id"]
    touch(fund)
    # Existing accounts begin the period with their current balance as opening.
    for account in db["capital_accounts"].values():
        sc = db["share_classes"].get(account["share_class_id"])
        if sc is not None and sc["fund_id"] == fund["id"] and account["status"] != "CLOSED":
            reset_period_accumulators(account, account["current_balance_cents"])
    return period
