"""Domain calculations, derived-field reconciliation, and cascade logic.

Every rule here traces to a PRD §3 sentence and a SCAFFOLD §1.3 calculation.
"""
import db
from common import (round_half_up, ceil_div, parse_dt, whole_utc_days,
                    stamp_create, touch)


# ===========================================================================
# Calculation 1: group_discount (PRD §3.10, SCAFFOLD group_discount)
# ===========================================================================
def group_discount_pct(active_line_count):
    """Table lookup keyed on active_line_count; exact, no rounding."""
    if active_line_count <= 1:
        return 0.00
    elif active_line_count == 2:
        return 0.05
    elif active_line_count == 3:
        return 0.10
    elif active_line_count == 4:
        return 0.15
    else:  # >= 5, capped
        return 0.20


def account_lines(account_id):
    return [l for l in db.lines.values() if l["account_id"] == account_id]


def count_active_lines(account_id):
    """Lines whose status IN {ACTIVE, SUSPENDED} (PRD §3.10)."""
    return sum(
        1 for l in account_lines(account_id)
        if l["status"] in ("ACTIVE", "SUSPENDED")
    )


def account_eip_outstanding(account_id):
    """Sum of remaining_balance_cents over ACTIVE InstallmentPlans on this
    account's lines (PRD §3.6)."""
    line_ids = {l["id"] for l in account_lines(account_id)}
    total = 0
    for ip in db.installment_plans.values():
        if ip["line_id"] in line_ids and ip["status"] == "ACTIVE":
            total += ip["remaining_balance_cents"]
    return total


def recompute_account_derived(account, bump_version):
    """Recompute active_line_count, group_discount_pct, total_eip_outstanding.

    Per PRD §2.5 these derived-field refreshes are mutations: each refreshes
    updated_at and bumps version. bump_version controls whether this particular
    recompute is the version-incrementing one for the triggering action.
    """
    alc = count_active_lines(account["id"])
    account["active_line_count"] = alc
    account["group_discount_pct"] = group_discount_pct(alc)
    account["total_eip_outstanding_cents"] = account_eip_outstanding(account["id"])
    if bump_version:
        touch(account)
    else:
        from common import clock_iso
        account["updated_at"] = clock_iso()


def recompute_eip_outstanding(account):
    """Recompute only total_eip_outstanding_cents (e.g. on EIP open/payoff).

    PRD §2.5: derived-field refreshes are mutations (updated_at + version bump).
    """
    account["total_eip_outstanding_cents"] = account_eip_outstanding(account["id"])
    touch(account)


# ===========================================================================
# Calculation 6: eip_schedule (PRD §3.6, SCAFFOLD eip_schedule)
# ===========================================================================
def eip_financed(retail_price_cents, down_payment_cents):
    return retail_price_cents - down_payment_cents


def eip_monthly_installment(financed_cents, term_months):
    """financed / term rounded UP to the next whole cent (ceiling)."""
    return ceil_div(financed_cents, term_months)


# ===========================================================================
# Calculation 2: line_overage (PRD §3.10, SCAFFOLD line_overage)
# ===========================================================================
def line_overage_cents(line, plan):
    over_mb = max(0, line.get("cycle_data_used_mb", 0) - plan["included_data_mb"])
    if over_mb == 0:
        return 0
    tier1_mb = min(over_mb, plan["overage_tier1_cap_mb"])
    tier2_mb = max(0, over_mb - plan["overage_tier1_cap_mb"])
    raw_milli = (tier1_mb * plan["overage_tier1_rate_milli_cents"]
                 + tier2_mb * plan["overage_tier2_rate_milli_cents"])
    return round_half_up(raw_milli, 1000)  # milli-cents -> cents, half-up


# ===========================================================================
# Calculation 3 & 4 helpers: discounted base and proration (PRD §3.10)
# ===========================================================================
def discounted_base_cents(plan, discount_pct):
    """monthly_fee * (1 - discount), rounded half-up. Rounds FIRST."""
    # round_half_up(monthly_fee_cents * (1 - pct)) — express with integers to
    # keep precision: fee * (1 - pct) = fee * ((100 - pct*100) / 100).
    factor_num = round(100 * (1 - discount_pct))  # e.g. 0.10 -> 90
    return round_half_up(plan["monthly_fee_cents"] * factor_num, 100)


def prorated_base_cents(discounted_base, active_days, days_in_cycle):
    """discounted_base * active_days / days_in_cycle, rounded half-up.

    round-the-discount-then-prorate (PRD §3.10): discount already rounded.
    """
    if days_in_cycle <= 0:
        return 0
    return round_half_up(discounted_base * active_days, days_in_cycle)


# ===========================================================================
# Active-day counting for a line within a cycle window (PRD §3.2/§3.10)
# ===========================================================================
def line_active_days(line, cycle):
    """Whole UTC days the line spent in {ACTIVE, SUSPENDED} within the cycle.

    Proration begins at activated_at (PRD §3.2). The line entered a billable
    state at activated_at and remains billable through the present (or cancel
    time). We intersect [activated_at, current/cancel) with the cycle window.
    """
    if not line.get("activated_at"):
        return 0
    cycle_start = parse_dt(cycle["cycle_start"], "cycle_start")
    cycle_end = parse_dt(cycle["cycle_end"], "cycle_end")
    activated = parse_dt(line["activated_at"], "activated_at")

    # End of billable interval: the line stops accruing base when cancelled,
    # otherwise it accrues through the cycle window's end (or current clock).
    end_instant = cycle_end
    if line["status"] == "CANCELLED" and line.get("_cancelled_at"):
        cancelled = parse_dt(line["_cancelled_at"], "_cancelled_at")
        if cancelled < end_instant:
            end_instant = cancelled
    now = db.now()
    if now < end_instant:
        end_instant = now

    start = max(activated, cycle_start)
    if end_instant <= start:
        return 0
    return whole_utc_days(start, end_instant)


def open_cycle_for_account(account_id):
    for c in db.billing_cycles.values():
        if c["account_id"] == account_id and c["status"] == "OPEN":
            return c
    return None


# ===========================================================================
# Add-on billing helpers (PRD §3.10) — used at usage-summary and cycle close.
# ===========================================================================
def addon_billed_days(addon, cycle, until=None):
    """For a daypass: number of whole UTC days billed within the cycle window.

    Billed window is the add-on's coverage intersected with the cycle, bounded
    by 'until' (current clock at summary time, or cycle_end at close). Cancelled
    add-ons keep already-elapsed days (PRD §3.8).
    """
    cycle_start = parse_dt(cycle["cycle_start"], "cycle_start")
    cycle_end = parse_dt(cycle["cycle_end"], "cycle_end")
    w_start = parse_dt(addon["window_start"], "window_start")
    w_end = parse_dt(addon["window_end"], "window_end")

    upper = until if until is not None else cycle_end
    seg_start = max(w_start, cycle_start)
    seg_end = min(w_end, cycle_end, upper)
    if seg_end <= seg_start:
        return 0
    return whole_utc_days(seg_start, seg_end)


def line_addon_cents(line, cycle, until=None):
    """Sum of add-on fees attributable to the cycle for this line (PRD §3.10).

    Daypass: daily_fee_cents * billed_days. Monthly: monthly_fee_cents if it
    was active during the cycle. Cancelled daypasses retain already-elapsed
    days; cancelled monthlies are not billed going forward.
    """
    total = 0
    for a in db.addons.values():
        if a["line_id"] != line["id"]:
            continue
        if a["addon_type"] == "ROAMING_DAYPASS":
            # daypass: already-elapsed billed days remain even after cancel
            days = addon_billed_days(a, cycle, until)
            total += (a.get("daily_fee_cents") or 0) * days
        else:  # INTL_MONTHLY
            # billed if it was ACTIVE during the cycle (window overlaps cycle)
            if a["status"] in ("ACTIVE", "EXPIRED"):
                cycle_start = parse_dt(cycle["cycle_start"], "cycle_start")
                cycle_end = parse_dt(cycle["cycle_end"], "cycle_end")
                w_start = parse_dt(a["window_start"], "window_start")
                w_end = parse_dt(a["window_end"], "window_end")
                if w_start < cycle_end and w_end > cycle_start:
                    total += (a.get("monthly_fee_cents") or 0)
    return total


def line_eip_installment_cents(line):
    """Sum of monthly_installment_cents across this line's ACTIVE EIPs."""
    return sum(
        ip["monthly_installment_cents"]
        for ip in db.installment_plans.values()
        if ip["line_id"] == line["id"] and ip["status"] == "ACTIVE"
    )


# ===========================================================================
# Add-on temporal reconciliation on read (PRD §3.11):
# "ACTIVE add-ons past their window_end are treated as EXPIRED on the next read"
# ===========================================================================
def reconcile_addon(addon):
    """Expire an ACTIVE add-on whose window_end has been reached by the clock."""
    if addon["status"] == "ACTIVE":
        w_end = parse_dt(addon["window_end"], "window_end")
        if db.now() >= w_end:
            addon["status"] = "EXPIRED"
            touch(addon)


def reconcile_all_addons():
    for a in db.addons.values():
        reconcile_addon(a)
