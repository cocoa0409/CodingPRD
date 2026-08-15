"""Calculation modules per SCAFFOLD §1.3 / PRD §3.

All money is integer cents; every computed amount rounds half-up to 0 dp.
"""
from decimal import Decimal

from util import dec, full_quarters_elapsed, parse_dt, round_half_up_decimal, round_half_up_div

QUARTERS_PER_YEAR = 4
COMPOUNDING_CARRY_THRESHOLD = Decimal("0.25")
RESERVE_PCT = Decimal("0.10")
DEBT_SERVICE_PCT = Decimal("0.30")


def preferred_return_accrual_cents(funded_cents, pref_rate, carry_pct, funded_at_iso, as_of) -> int:
    """Lifetime preferred-return accrual (calc preferred_return_accrual, PRD 3.8).

    simple:                round_half_up(P * r * Q/4)             when promote < 0.25
    compounding_quarterly: round_half_up(P * ((1 + r/4)^Q - 1))   when promote >= 0.25
    Q = full calendar quarters between funded_at and the as-of instant.
    """
    if not funded_at_iso or not funded_cents or funded_cents <= 0:
        return 0
    if pref_rate is None or carry_pct is None:
        return 0
    q = full_quarters_elapsed(parse_dt(funded_at_iso), as_of)
    if q <= 0:
        return 0
    r = dec(pref_rate)
    promote = dec(carry_pct)
    principal = Decimal(int(funded_cents))
    if promote >= COMPOUNDING_CARRY_THRESHOLD:
        base = Decimal(1) + r / QUARTERS_PER_YEAR
        acc = principal * (base ** q - 1)
    else:
        acc = principal * r * q / QUARTERS_PER_YEAR
    return round_half_up_decimal(acc)


def waterfall_allocate(pool_cents, lps, promote):
    """Four-tier distribution waterfall (calc distribution_waterfall_allocation).

    lps: FUNDED subscriptions pre-sorted by funded_at ASC, created_at ASC, each a
    dict {subscription_id, unreturned_capital_cents, accrued_pref_cents, funded_cents}.
    Per-line round half-up, rounded lines summed — NO reconciliation pass.
    Returns one line dict per LP in the same order.
    """
    promote = dec(promote)
    n = len(lps)
    t1 = [0] * n
    t2 = [0] * n
    t3 = [0] * n
    t4lp = [0] * n
    t4gp = [0] * n

    # Tier 1 — return of capital, dealt in LP order.
    pool1 = min(pool_cents, sum(max(0, l["unreturned_capital_cents"]) for l in lps))
    rem = pool1
    for i, l in enumerate(lps):
        amt = min(max(0, l["unreturned_capital_cents"]), rem)
        t1[i] = amt
        rem -= amt
    sum_t1 = sum(t1)

    # Tier 2 — preferred return, dealt in LP order.
    pool2 = min(pool_cents - sum_t1, sum(max(0, l["accrued_pref_cents"]) for l in lps))
    rem = pool2
    for i, l in enumerate(lps):
        amt = min(max(0, l["accrued_pref_cents"]), rem)
        t2[i] = amt
        rem -= amt
    sum_t2 = sum(t2)

    # Tier 3 — GP catch-up, attributed pro-rata to tier-2 amounts.
    one_minus = Decimal(1) - promote
    if one_minus <= 0:
        catch_up_total = pool_cents - sum_t1 - sum_t2
    else:
        catch_up_total = round_half_up_decimal(promote * sum_t2 / one_minus)
    pool3 = min(pool_cents - sum_t1 - sum_t2, catch_up_total)
    denom2 = max(sum_t2, 1)
    for i, l in enumerate(lps):
        t3[i] = round_half_up_div(pool3 * t2[i], denom2)

    # Tier 4 — residual profit split, pro-rata by funded_cents on each side.
    residual = pool_cents - sum_t1 - sum_t2 - pool3
    lp_side = round_half_up_decimal(Decimal(residual) * one_minus)
    gp_side = residual - lp_side
    funded_total = max(sum(l["funded_cents"] for l in lps), 1)
    for i, l in enumerate(lps):
        t4lp[i] = round_half_up_div(lp_side * l["funded_cents"], funded_total)
        t4gp[i] = round_half_up_div(gp_side * l["funded_cents"], funded_total)

    out = []
    for i, l in enumerate(lps):
        out.append({
            "subscription_id": l["subscription_id"],
            "return_of_capital_cents": t1[i],
            "preferred_return_cents": t2[i],
            "profit_split_lp_cents": t4lp[i],
            "profit_split_gp_cents": t3[i] + t4gp[i],
            "total_cents": t1[i] + t2[i] + t4lp[i] + t3[i] + t4gp[i],
        })
    return out


def capital_call_prorata(total_call_cents, eligible):
    """Pro-rata capital-call lines (calc capital_call_prorata_allocation).

    eligible: subscriptions in created_at ASC order, each a dict
    {subscription_id, committed_cents, seq}. Per-line round half-up, then the
    signed remainder goes to the single largest line (ties: earliest created).
    Returns {subscription_id: amount_due_cents} summing exactly to the call.
    """
    total_committed = sum(e["committed_cents"] for e in eligible)
    if not eligible or total_committed <= 0:
        return {}
    lines = {}
    for e in eligible:
        lines[e["subscription_id"]] = round_half_up_div(
            total_call_cents * e["committed_cents"], total_committed
        )
    diff = total_call_cents - sum(lines.values())
    if diff != 0:
        best = max(eligible, key=lambda e: (lines[e["subscription_id"]], -e["seq"]))
        lines[best["subscription_id"]] += diff
    return lines


def quarterly_distributable_cash_cents(noi_cents) -> int:
    """calc quarterly_distributable_cash: NOI less 10% reserve and 30% debt service."""
    reserve = round_half_up_decimal(Decimal(int(noi_cents)) * RESERVE_PCT)
    debt = round_half_up_decimal(Decimal(int(noi_cents)) * DEBT_SERVICE_PCT)
    return max(0, int(noi_cents) - reserve - debt)


def capital_event_net_distributable(gross_proceeds_cents, debt_payoff_cents) -> int:
    """calc capital_event_net_distributable: exact integer subtraction."""
    return int(gross_proceeds_cents) - int(debt_payoff_cents)


def k1_allocation(noi_cents, lps, reconcile):
    """K-1 allocation (calc k1_provisional_allocation / k1_final_allocation).

    lps: FUNDED subscriptions pre-sorted by funded_at ASC, created_at ASC, each a
    dict {subscription_id, funded_cents, seq}. Per-line round half-up; when
    reconcile=True (final variant) the signed remainder goes to the line with the
    largest funded_cents (ties: earliest created_at) so the map sums to the NOI.
    """
    total = sum(l["funded_cents"] for l in lps)
    if not lps or total <= 0:
        return {}
    lines = {
        l["subscription_id"]: round_half_up_div(noi_cents * l["funded_cents"], total)
        for l in lps
    }
    if reconcile:
        diff = noi_cents - sum(lines.values())
        if diff != 0:
            best = max(lps, key=lambda l: (l["funded_cents"], -l["seq"]))
            lines[best["subscription_id"]] += diff
    return lines


def transfer_carryover(from_funded_cents, transfer_cents, accrued_pref_cents, unreturned_capital_cents):
    """Pro-rata carryover (calc transfer_prorata_carryover).

    ratio = T / F on the pre-settlement funded balance; each carried amount is
    round_half_up(stored * ratio).
    """
    if from_funded_cents <= 0:
        return 0, 0
    carry_pref = round_half_up_div(accrued_pref_cents * transfer_cents, from_funded_cents)
    carry_unret = round_half_up_div(unreturned_capital_cents * transfer_cents, from_funded_cents)
    return carry_pref, carry_unret
