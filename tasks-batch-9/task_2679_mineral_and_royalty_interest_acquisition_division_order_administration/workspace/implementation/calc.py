"""Every calculation rule from SCAFFOLD calculations / PRD section 3.

All rounding is round-half-up (PRD 2.5).  Nothing here uses float.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP

from db import clock_date, clock_dt, db
from errors import ApiError

ZERO = Decimal("0")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def q6(value):
    return q(value, 6)


def q8(value):
    return q(value, 8)


# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
BURDEN_CAP = Decimal("0.2500")
DISCOUNT_RATE_ANNUAL = Decimal("0.10")
HORIZON_YEARS = 5
RISK_FACTOR_UNDEVELOPED = Decimal("0.45")
UPSIDE_PER_NET_ACRE = Decimal("1800.00")
ACTIVITY_MULTIPLIER = {
    "HIGH": Decimal("1.20"),
    "MODERATE": Decimal("1.00"),
    "LOW": Decimal("0.80"),
}
MAX_COUNTER_ROUNDS = 3
PSA_WINDOW_BUFFER_DAYS = 30
PSA_TERMINATION_THRESHOLD_PCT = Decimal("0.20")
DEFAULT_CURATIVE_DAYS = 45
NON_CONSENT_PENALTY_PCT = Decimal("0.30")
SUSPENSE_INTEREST_ANNUAL = Decimal("0.06")
ESCHEAT_MONTHS = 36
DEPLETION_RATE = Decimal("0.15")
DEPLETION_INCOME_CAP_PCT = Decimal("0.65")

SEVERANCE_RATES = {
    "TX": {"OIL": Decimal("0.046000"), "GAS": Decimal("0.075000"), "NGL": Decimal("0.046000")},
    "OK": {"OIL": Decimal("0.070000"), "GAS": Decimal("0.070000"), "NGL": Decimal("0.070000")},
    "NM": {"OIL": Decimal("0.037500"), "GAS": Decimal("0.037500"), "NGL": Decimal("0.037500")},
    "ND": {"OIL": Decimal("0.050000"), "GAS": Decimal("0.065000"), "NGL": Decimal("0.050000")},
}


# --------------------------------------------------------------------------
# chain of title replay
# --------------------------------------------------------------------------
def chain_entries_of(tract_id):
    """Replay order: instrument_date ASC, then created_at ASC.  Never id."""
    rows = [e for e in db.chain_entries.values() if e["tract_id"] == tract_id]
    return sorted(rows, key=lambda e: (e["instrument_date"], e["_seq"]))


def net_mineral_acres_from_chain(tract):
    """Chronological replay; rounding applied after every step.  Raises
    ERR_CHAIN_ACREAGE_NEGATIVE the moment the running figure goes below zero."""
    acres = Decimal("0.0000")
    for entry in chain_entries_of(tract["id"]):
        kind = entry["instrument_type"]
        if kind == "PATENT":
            acres = q4(tract["gross_acres"] * entry["conveyed_fraction"])
        elif kind == "DEED":
            acres = q4(acres - entry["conveyed_acres"])
        elif kind == "PROBATE":
            acres = q4(acres * entry["conveyed_fraction"])
        else:  # ASSIGNMENT leaves the running acreage exactly as it was
            acres = q4(acres)
        if acres < 0:
            raise ApiError("ERR_CHAIN_ACREAGE_NEGATIVE")
    return acres


def tract_burden_fraction(tract):
    """Only ASSIGNMENT entries contribute; a plain, order-insensitive sum."""
    total = ZERO
    for entry in chain_entries_of(tract["id"]):
        if entry["instrument_type"] == "ASSIGNMENT":
            total += entry["conveyed_fraction"]
    raw = q4(total)
    if raw > BURDEN_CAP:
        raise ApiError("ERR_BURDEN_CAP_EXCEEDED")
    return raw


# --------------------------------------------------------------------------
# decline-curve valuation
# --------------------------------------------------------------------------
def valuation_bid_band(current_monthly_net_revenue, annual_decline_rate,
                       undeveloped_net_acres, activity_tier, burden_fraction):
    pdp_pv = Decimal("0.00")
    base = dec(current_monthly_net_revenue)
    decline = dec(annual_decline_rate)
    for year in range(1, HORIZON_YEARS + 1):
        annual_y = q2(base * 12 * ((Decimal(1) - decline) ** (year - 1)))
        discounted_y = q2(annual_y / ((Decimal(1) + DISCOUNT_RATE_ANNUAL) ** year))
        pdp_pv = q2(pdp_pv + discounted_y)

    undeveloped_pv = q2(
        dec(undeveloped_net_acres)
        * UPSIDE_PER_NET_ACRE
        * RISK_FACTOR_UNDEVELOPED
        * ACTIVITY_MULTIPLIER[activity_tier]
    )
    haircut = Decimal(1) - dec(burden_fraction)
    bid_floor = q2(pdp_pv * haircut)
    max_bid = q2((pdp_pv + undeveloped_pv) * haircut)
    return pdp_pv, undeveloped_pv, bid_floor, max_bid


# --------------------------------------------------------------------------
# expected decimal interest
# --------------------------------------------------------------------------
def allocations_for_pair(unit_id, tract_id):
    return [a for a in db.allocations.values()
            if a["unit_id"] == unit_id and a["tract_id"] == tract_id]


def select_allocation(unit, tract_id):
    """Deterministic allocation selector (PRD 3.8).  Rungs 42 and 44 are disjoint
    by construction: rung 44 (ERR_TRACT_UNIT_MISMATCH, priority 74) fires only
    when the pair has never been allocated in any posture over any interval,
    while rung 42 (ERR_NO_ACTIVE_ALLOCATION, priority 72) fires only once such a
    row exists but none covers the logical clock date.  Rung 43
    (ERR_ALLOCATION_NOT_ACTIVE, priority 73) fires on the selected candidate."""
    rows = allocations_for_pair(unit["id"], tract_id)
    today = clock_date()
    covering = []
    for row in rows:
        if row["_effective_from_date"] <= today < row["_effective_to_date"]:
            covering.append(row)
    if not rows:
        raise ApiError("ERR_TRACT_UNIT_MISMATCH")
    if not covering:
        raise ApiError("ERR_NO_ACTIVE_ALLOCATION")
    covering.sort(key=lambda a: (a["effective_from"], a["_seq"]), reverse=True)
    chosen = covering[0]
    if chosen["allocation_status"] not in ("ACTIVE", "PUGH_RELEASED"):
        raise ApiError("ERR_ALLOCATION_NOT_ACTIVE")
    return chosen


def expected_decimal_interest(interest, tract, unit, allocation):
    ownership = dec(interest["net_mineral_acres"]) / dec(tract["gross_acres"])
    participation = dec(allocation["allocated_acres"]) / dec(unit["unit_gross_acres"])
    election = allocation["pooling_election"]
    lease_rate = dec(interest["lease_royalty_rate"])
    cap = dec(unit["royalty_rate_cap"])
    if election == "LEASED_ROYALTY_ONLY":
        effective_rate = lease_rate
        election_factor = Decimal("1")
    elif election == "NON_CONSENT":
        effective_rate = lease_rate if lease_rate < cap else cap
        election_factor = q4(Decimal(1) - NON_CONSENT_PENALTY_PCT)
    else:  # POOLED
        effective_rate = lease_rate if lease_rate < cap else cap
        election_factor = Decimal("1")
    net_burden = q6(effective_rate - dec(interest["existing_burden_fraction"]))
    if net_burden < 0:
        net_burden = Decimal("0.000000")
    return q8(ownership * participation * net_burden * election_factor)


def compute_expected_decimal(interest, unit):
    tract = db.tracts[interest["tract_id"]]
    allocation = select_allocation(unit, interest["tract_id"])
    return expected_decimal_interest(interest, tract, unit, allocation), allocation


def try_compute_expected_decimal(interest, unit):
    """Cascade-safe variant: a cascade must never fail the triggering request."""
    try:
        return compute_expected_decimal(interest, unit)
    except ApiError:
        return None, None


# --------------------------------------------------------------------------
# defect basket waterfall
# --------------------------------------------------------------------------
def defect_values(psa, interest, affected_nma):
    allocated_value = q2(dec(psa["purchase_price"]) * dec(affected_nma)
                         / dec(interest["net_mineral_acres"]))
    net_value = allocated_value - dec(psa["individual_defect_threshold"])
    if net_value < 0:
        net_value = ZERO
    return allocated_value, q2(net_value)


def defect_price_adjustment(psa, interest, uncured_defects):
    """Per-defect rounding first, then accumulation (the pinned order)."""
    sum_net = Decimal("0.00")
    for defect in sorted(uncured_defects, key=lambda d: d["_seq"]):
        allocated_value, net_value = defect_values(psa, interest, defect["affected_nma"])
        defect["allocated_value"] = allocated_value
        defect["net_defect_value"] = net_value
        sum_net = q2(sum_net + net_value)
    basket = dec(psa["aggregate_defect_basket"])
    if sum_net <= basket:
        adjustment = Decimal("0.00")
    else:
        adjustment = q2(sum_net - basket)
    ceiling = q2(dec(psa["purchase_price"]) * PSA_TERMINATION_THRESHOLD_PCT)
    return adjustment, ceiling


# --------------------------------------------------------------------------
# revenue reconciliation
# --------------------------------------------------------------------------
def severance_rate(state_code, product_code):
    return SEVERANCE_RATES[state_code][product_code]


def net_after_tax(gross, rate):
    return q2(gross - q2(gross * rate))


# --------------------------------------------------------------------------
# suspense accrual
# --------------------------------------------------------------------------
def months_between(first_month, now=None):
    now = now or clock_dt()
    year = int(first_month[0:4])
    month = int(first_month[5:7])
    return (now.year - year) * 12 + (now.month - month)


def suspense_interest(accrued_amount, months_held):
    return q2(dec(accrued_amount) * SUSPENSE_INTEREST_ANNUAL * months_held / Decimal(12))


# --------------------------------------------------------------------------
# owner annual tax statement
# --------------------------------------------------------------------------
def owner_tax_statement(owner_id, tax_year):
    order_ids = set(o["id"] for o in db.division_orders.values()
                    if o["royalty_owner_id"] == owner_id)
    low = "%04d-01" % tax_year
    high = "%04d-12" % tax_year
    gross = ZERO
    tax = ZERO
    count = 0
    for detail in db.revenue_details.values():
        if detail["division_order_id"] not in order_ids:
            continue
        if detail["check_status"] != "PAID":
            continue
        if not (low <= detail["production_month"] <= high):
            continue
        gross += detail["reported_gross_royalty"]
        tax += detail["severance_tax_amount"]
        count += 1
    gross_royalty = q2(gross)
    severance_tax_withheld = q2(tax)
    taxable_before_depletion = q2(gross_royalty - severance_tax_withheld)
    statutory = DEPLETION_RATE * gross_royalty
    income_cap = DEPLETION_INCOME_CAP_PCT * taxable_before_depletion
    depletion_allowance = q2(statutory if statutory < income_cap else income_cap)
    net_taxable = q2(taxable_before_depletion - depletion_allowance)
    return {
        "royalty_owner_id": owner_id,
        "tax_year": tax_year,
        "gross_royalty": gross_royalty,
        "severance_tax_withheld": severance_tax_withheld,
        "taxable_before_depletion": taxable_before_depletion,
        "depletion_allowance": depletion_allowance,
        "net_taxable": net_taxable,
        "detail_count": count,
    }


# --------------------------------------------------------------------------
# date helpers
# --------------------------------------------------------------------------
def add_days(date_obj, days):
    return date_obj + datetime.timedelta(days=days)


def date_to_str(date_obj):
    return "%04d-%02d-%02d" % (date_obj.year, date_obj.month, date_obj.day)
