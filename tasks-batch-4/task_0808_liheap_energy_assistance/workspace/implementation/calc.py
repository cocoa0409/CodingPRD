"""Calculation rules (§1.3 / PRD §3.4, §3.7, §3.8, §3.9) and derived helpers."""
from decimal import Decimal, ROUND_HALF_UP

from store import db, public

# ---- Income eligibility (§3.4) -------------------------------------------
FPL_ANNUAL_CENTS = {
    1: 1506000, 2: 2044000, 3: 2582000, 4: 3120000,
    5: 3658000, 6: 4196000, 7: 4734000, 8: 5272000,
}
FPL_ADDL_PER_PERSON_CENTS = 538000
ELIGIBILITY_FPL_PCT = Decimal("150.00")


def fpl_annual_cents(size):
    base = FPL_ANNUAL_CENTS[min(size, 8)]
    if size > 8:
        base += FPL_ADDL_PER_PERSON_CENTS * (size - 8)
    return base


def compute_fpl_pct(income_cents, size):
    """Return fpl_pct as a Decimal rounded half-up to 2 places."""
    val = (Decimal(income_cents) / Decimal(fpl_annual_cents(size))) * Decimal(100)
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- Benefit tier + award (§3.4) -----------------------------------------
TIER_BASE_CENTS = {"TIER_1": 81500, "TIER_2": 61000, "TIER_3": 40500}
HEATING_FACTOR = {
    "ELECTRICITY": Decimal("1.0"),
    "NATURAL_GAS": Decimal("1.1"),
    "FUEL_OIL": Decimal("1.3"),
    "PROPANE": Decimal("1.25"),
}
VULNERABILITY_SUPPLEMENT_CENTS = 15000
MAX_BENEFIT_CENTS = 150000
MIN_BENEFIT_CENTS = 10000


def benefit_tier_from_pct(pct):
    if pct <= Decimal("75"):
        return "TIER_1"
    if pct <= Decimal("110"):
        return "TIER_2"
    if pct <= Decimal("150"):
        return "TIER_3"
    return "INELIGIBLE"


def _round_dollar(cents_decimal):
    """Round a cent value to the nearest whole dollar (multiple of 100 cents), half-up."""
    dollars = (cents_decimal / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return dollars * Decimal(100)


def compute_benefit_amount(tier, household_size, heating_source, vulnerable):
    if tier not in TIER_BASE_CENTS:
        return 0
    base = TIER_BASE_CENTS[tier]
    size_mult = Decimal("1.0") + Decimal("0.10") * Decimal(max(0, household_size - 2))
    hf = HEATING_FACTOR[heating_source]
    size_component = Decimal(base) * size_mult
    heating_component = Decimal(base) * (hf - Decimal("1.0"))
    vulnerability_component = Decimal(VULNERABILITY_SUPPLEMENT_CENTS) if vulnerable else Decimal(0)
    # PINNED: round each component to whole dollars THEN sum (round-then-sum).
    raw_sum = _round_dollar(size_component) + _round_dollar(heating_component) + vulnerability_component
    raw = int(raw_sum)
    return min(MAX_BENEFIT_CENTS, max(MIN_BENEFIT_CENTS, raw))


# ---- Crisis flat rates (§3.8) --------------------------------------------
CRISIS_RATE_CENTS = {"NO_HEAT": 50000, "DISCONNECTION_NOTICE": 40000, "OUT_OF_FUEL": 60000}
CRISIS_DEADLINE_HOURS = 48


# ---- Bill-credit waterfall (§3.7) ----------------------------------------
def bill_credit_allocation(credit_cents, arrearage_cents, current_balance_cents):
    """Arrearage-first waterfall. Returns (applied_to_arrearage, applied_to_current)."""
    applied_arr = min(credit_cents, arrearage_cents)
    remaining = credit_cents - applied_arr
    applied_cur = min(remaining, current_balance_cents)
    return applied_arr, applied_cur


# ---- Referral priority (§3.9) --------------------------------------------
def referral_priority(reason, has_elderly_or_disabled, has_child_under_6):
    if reason == "TIER_1_AUTO" or has_elderly_or_disabled:
        return "HIGH"
    if has_child_under_6:
        return "MEDIUM"
    return "LOW"


# ---- Funding-pool ledger derivation (§2.7, §3.1) -------------------------
def pool_balances(pool):
    """Recompute reserved/disbursed/available and derive status for a pool."""
    reserved = 0
    disbursed = 0
    pid = pool["id"]
    for pl in db.pledges.values():
        if pl["funding_pool_id"] != pid:
            continue
        if pl["status"] == "PLEDGED":
            reserved += pl["pledged_amount_cents"]
        elif pl["status"] == "PAID":
            disbursed += pl["pledged_amount_cents"]
    available = pool["total_allocation_cents"] - reserved - disbursed
    if pool.get("_closed"):
        status = "CLOSED"
    elif available == 0:
        status = "DEPLETED"
    elif 0 < available <= pool["depletion_threshold_cents"]:
        status = "LOW"
    else:
        status = "OPEN"
    return reserved, disbursed, available, status


def pool_status(pool):
    return pool_balances(pool)[3]


def pool_available(pool):
    return pool_balances(pool)[2]


def serialize_pool(pool):
    reserved, disbursed, available, status = pool_balances(pool)
    out = public(pool)
    out["reserved_cents"] = reserved
    out["disbursed_cents"] = disbursed
    out["available_cents"] = available
    out["status"] = status
    return out
