"""Core calculations: vesting, exercise price, withholding tax, proceeds."""

from decimal import Decimal, ROUND_HALF_UP
from db import DB
from services.time_util import (
    parse_iso, format_iso, add_months, floor_months_between, days_between
)

DAYS_PER_MONTH = 30
BPS_DIVISOR = 10000
MIN_PRICE_CENTS = 1
LONG_TERM_HOLDING_MONTHS = 12
LONG_TERM_DISCOUNT_BPS = 1000


def floor_div(a, b):
    # Integer floor division (a, b are ints, b > 0)
    return a // b


def round_half_up_int(numerator, denominator):
    """Compute round-half-up(numerator/denominator) as an integer."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -----------------------------------------------------------------------------
# Vesting
# -----------------------------------------------------------------------------

def _vested_records_sum(grant_id, causes):
    total = 0
    for vr in DB["vesting_records"].values():
        if vr["grant_id"] != grant_id:
            continue
        if vr["cause"] in causes:
            total += int(vr["tranche_quantity"])
    return total


def compute_vested_quantity(grant, plan, batch, at_clock_dt=None):
    """Return the vested_quantity for a grant at the given clock time.

    at_clock_dt is a datetime; defaults to plan.current_clock_ts.
    Returns 0 if the grant has no grant_date (pre-board-approval) or
    no clock has been set.
    """
    if grant.get("grant_date") is None:
        return 0

    clock = at_clock_dt if at_clock_dt is not None else parse_iso(plan.get("current_clock_ts"))
    grant_date = parse_iso(grant["grant_date"])
    if clock is None or grant_date is None:
        return 0

    cliff_months = int(batch["cliff_months"])
    vesting_total_months = int(batch["vesting_total_months"])
    vesting_period_months = int(batch["vesting_period_months"])
    algorithm = batch["vesting_algorithm"]
    quantity = int(grant["quantity"])

    # PRD §3.5: "The constant DAYS_PER_MONTH is fixed at 30, so the number
    # of days from grant date to cliff is cliff_months multiplied by 30..."
    # The cliff threshold check uses the same 30-day month convention so
    # that "whole months elapsed" is consistent across algorithms.
    days_elapsed = days_between(grant_date, clock)
    months_elapsed = max(0, days_elapsed) // DAYS_PER_MONTH
    if months_elapsed < cliff_months:
        unconditional = 0
    elif algorithm == "ANNIVERSARY_BATCH":
        # tranches at each vesting_period_months boundary AFTER the cliff
        # completed_periods = floor((months_elapsed - cliff_months)/period) + 1
        diff = months_elapsed - cliff_months
        completed = (diff // vesting_period_months) + 1
        cap = vesting_total_months // vesting_period_months
        if completed > cap:
            completed = cap
        # floor(quantity * completed * period / total_months)
        unconditional = (quantity * completed * vesting_period_months) // vesting_total_months
    elif algorithm == "CONTINUOUS_DAILY":
        # PRD §3.5: cliff offset is cliff_months * 30 days; total vesting
        # days is vesting_total_months * 30; days-since-cliff is the
        # day-count between grant_date + cliff and the plan clock.
        cliff_days = cliff_months * DAYS_PER_MONTH
        days_since_cliff = max(0, days_elapsed - cliff_days)
        total_vesting_days = (vesting_total_months * DAYS_PER_MONTH) - (cliff_months * DAYS_PER_MONTH)
        if total_vesting_days <= 0:
            unconditional = quantity  # degenerate edge
        else:
            cap_days = min(days_since_cliff, total_vesting_days)
            unconditional = (quantity * cap_days) // total_vesting_days
    else:
        unconditional = 0

    if batch.get("performance_condition_required") and grant.get("performance_attested_at") is None:
        gated = 0
    else:
        gated = unconditional

    accelerated = _vested_records_sum(
        grant["id"],
        {"ACCELERATION_CHANGE_OF_CONTROL", "ACCELERATION_IPO"},
    )

    return min(quantity, max(gated, accelerated))


# -----------------------------------------------------------------------------
# Exercise price per version
# -----------------------------------------------------------------------------

def compute_price_for_event(parent_price_cents, event):
    cause = event["event_type"]
    if cause == "STOCK_SPLIT":
        num = int(event["split_ratio_numerator"])
        den = int(event["split_ratio_denominator"])
        return max(MIN_PRICE_CENTS, (parent_price_cents * den) // num)
    elif cause == "CASH_DIVIDEND":
        return max(MIN_PRICE_CENTS, parent_price_cents - int(event["dividend_amount_cents"]))
    elif cause == "RESTRUCTURING":
        bps = int(event["restructure_factor_bps"])
        new_price = round_half_up_int(parent_price_cents * bps, BPS_DIVISOR)
        return max(MIN_PRICE_CENTS, new_price)
    return parent_price_cents


# -----------------------------------------------------------------------------
# Withholding tax
# -----------------------------------------------------------------------------

# Marginal-rate slab tables keyed by (plan_jurisdiction, residency, event_type)
MAX_INT = 10 ** 18

_RATE_TABLE = {
    # Same-jurisdiction same-residency
    ("US", "US", "EXERCISE"): [(0, 1_000_000, 2200), (1_000_000, MAX_INT, 3700)],
    ("US", "US", "VEST"):     [(0, MAX_INT, 2200)],
    ("UK", "UK", "EXERCISE"): [(0, 5_000_000, 2000), (5_000_000, MAX_INT, 4500)],
    ("CN", "CN", "EXERCISE"): [(0, 3_600_000, 2000), (3_600_000, MAX_INT, 4500)],
    ("SG", "SG", "EXERCISE"): [(0, MAX_INT, 1500)],
    # Cross-residency exercises for US-plan
    ("US", "UK", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("US", "CN", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("US", "SG", "EXERCISE"): [(0, MAX_INT, 1500)],
    # Mirror cross-residency for other plan jurisdictions
    ("UK", "US", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("UK", "CN", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("UK", "SG", "EXERCISE"): [(0, MAX_INT, 1500)],
    ("CN", "US", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("CN", "UK", "EXERCISE"): [(0, MAX_INT, 3000)],
    ("CN", "SG", "EXERCISE"): [(0, MAX_INT, 1500)],
    ("SG", "US", "EXERCISE"): [(0, MAX_INT, 1500)],
    ("SG", "UK", "EXERCISE"): [(0, MAX_INT, 1500)],
    ("SG", "CN", "EXERCISE"): [(0, MAX_INT, 1500)],
    # VEST events are zero for non-US plans (no entries needed; default below)
    # SALE events use flat 2500 bps as a fallback minus long-term discount
    ("US", "US", "SALE"): [(0, MAX_INT, 2500)],
    ("UK", "UK", "SALE"): [(0, MAX_INT, 2500)],
    ("CN", "CN", "SALE"): [(0, MAX_INT, 2500)],
    ("SG", "SG", "SALE"): [(0, MAX_INT, 0)],
}


def _lookup_tiers(plan_jurisdiction, residency, event_type):
    key = (plan_jurisdiction, residency, event_type)
    return _RATE_TABLE.get(key)


def _apply_long_term_discount(tiers, long_term):
    if not long_term:
        return tiers
    return [(lo, hi, max(0, rate - LONG_TERM_DISCOUNT_BPS)) for (lo, hi, rate) in tiers]


def compute_withholding(taxable_amount_cents, plan_jurisdiction, residency, event_type, long_term=False):
    """Slab-by-slab marginal-rate computation; round-half-up per slab then sum.

    Returns the withheld amount in integer cents.
    """
    if taxable_amount_cents <= 0:
        return 0
    tiers = _lookup_tiers(plan_jurisdiction, residency, event_type)
    if not tiers:
        return 0
    tiers = _apply_long_term_discount(tiers, long_term)

    withheld = 0
    cursor = 0
    total = int(taxable_amount_cents)
    for (lo, hi, rate_bps) in tiers:
        # Portion of [cursor, cursor+remaining) that falls in [lo, hi)
        slab_lo = max(cursor, lo)
        slab_hi = min(total, hi)
        slab = max(0, slab_hi - slab_lo)
        if slab > 0:
            withheld += round_half_up_int(slab * rate_bps, BPS_DIVISOR)
            cursor = slab_hi
        if cursor >= total:
            break
    return withheld


def has_deferral_approved(grantee_id):
    """Return True iff there is a prior TaxEventRecord of event_type=GRANT with
    payload_summary.deferral_approved == True for this grantee."""
    for te in DB["tax_events"].values():
        if te["event_type"] != "GRANT":
            continue
        # link via grant -> grantee
        grant = DB["grants"].get(te["grant_id"])
        if not grant:
            continue
        if grant["grantee_id"] != grantee_id:
            continue
        payload = te.get("payload_summary") or {}
        if isinstance(payload, dict) and payload.get("deferral_approved") is True:
            return True
    return False


def compute_tax_for_event(plan, grant, grantee, event_type, *,
                           tranche_quantity=None,
                           exercise_app=None,
                           current_fair_value_cents=None,
                           pinned_price_cents=None,
                           sale_proceeds_cents=None,
                           cost_basis_cents=None,
                           sold_quantity=None,
                           holding_months=None):
    """Compute (taxable_amount_cents, withheld_amount_cents, deferred).

    Branches by event_type per spec.
    """
    plan_j = plan["jurisdiction_code"]
    residency = grantee["tax_residency"] if grantee else plan_j

    if event_type == "GRANT":
        taxable = 0
    elif event_type == "VEST":
        if plan_j == "US":
            taxable = int(tranche_quantity or 0) * int(grant["grant_date_fair_value_cents"])
        else:
            taxable = 0
    elif event_type == "EXERCISE":
        cur = current_fair_value_cents if current_fair_value_cents is not None else int(grant["grant_date_fair_value_cents"])
        pin = int(pinned_price_cents or 0)
        spread = max(0, cur - pin)
        req = int(exercise_app["requested_quantity"]) if exercise_app else 0
        taxable = spread * req
    elif event_type == "SALE":
        per_unit = int(sale_proceeds_cents or 0) - int(cost_basis_cents or 0)
        taxable = per_unit * int(sold_quantity or 0)
    else:
        taxable = 0

    long_term = False
    if event_type == "SALE" and holding_months is not None and holding_months >= LONG_TERM_HOLDING_MONTHS:
        long_term = True

    withheld = compute_withholding(taxable, plan_j, residency, event_type, long_term=long_term)

    deferred = False
    if (event_type == "EXERCISE"
            and plan_j == "UK"
            and grantee
            and grantee["tax_residency"] == "UK"
            and has_deferral_approved(grantee["id"])):
        deferred = True
        withheld = 0

    return taxable, withheld, deferred
