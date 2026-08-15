"""Calculation rules (scaffold Table 3): pricing, lead times, labor, valuation.

All money math uses exact integer arithmetic with round-half-up (PRD 2.5).
Per-unit rounding precedes extension; the alternative order is rejected.
"""
from datetime import timedelta

from errors import raise_error, ERR_INVALID_REQUEST
from util import round_half_up_int, add_calendar_days, add_business_days

MAX_DISCOUNT_PCT = 55
VOLUME_FEE_BAND_CENTS = 5_000_000
FEE_PCT_HIGH_VOLUME = 8
FEE_PCT_DEFAULT = 12
RESTOCK_PCT = 20
MIN_RESTOCK_FEE_CENTS = 25_000

EST_VALUE_PER_ITEM_CENTS = {"A": 120_000, "B": 75_000, "C": 30_000}
ESTIMATION_ASSUMED_GRADE = "B"
ESTIMATION_HAIRCUT_PCT = 20
LIQUIDATION_FEE_PCT = 15
REFURB_FEE_PER_ITEM_CENTS = {"A": 5_000, "B": 15_000, "C": 25_000}
APPRAISAL_VALIDITY_DAYS = 30


def selected_option_entries(series, selected_options):
    """Resolve option codes against the series catalog; unknown codes -> 400."""
    catalog = series.get("option_catalog") or []
    entries = []
    for code in selected_options:
        match = next((o for o in catalog if o.get("option_code") == code), None)
        if match is None:
            raise_error(ERR_INVALID_REQUEST, f"unknown option code '{code}' for series {series['series_code']}")
        entries.append(match)
    return entries


def configured_unit_list_price(series, selected_options) -> int:
    """configured_unit_list_price: base * (1 + sum(uplift_pct)/100), half-up."""
    entries = selected_option_entries(series, selected_options)
    uplift_sum = sum(int(o.get("price_uplift_pct", 0)) for o in entries)
    return round_half_up_int(series["base_list_price_cents"] * (100 + uplift_sum), 100)


def resolve_discount_pct(contract, category, quantity) -> int:
    """contract_net_unit_price tier resolution: highest min_qty <= quantity
    within the line's category (inclusive); else the contract default."""
    tiers = [
        t for t in (contract.get("pricing_tiers") or [])
        if t.get("category") == category and int(t.get("min_qty", 0)) <= quantity
    ]
    if tiers:
        applicable = max(tiers, key=lambda t: int(t.get("min_qty", 0)))
        return int(applicable.get("discount_pct", 0))
    return int(contract.get("default_discount_pct", 0))


def unit_net_price(unit_list_price_cents, discount_pct) -> int:
    """Per-unit rounding BEFORE extension (per_line_extension_rounding)."""
    return round_half_up_int(unit_list_price_cents * (100 - discount_pct), 100)


def price_line(line, series, contract):
    """Recompute a line's unit prices and line total. Replacement lines are
    warranty-priced at zero."""
    if line.get("is_replacement"):
        line["unit_list_price_cents"] = 0
        line["unit_net_price_cents"] = 0
        line["line_total_cents"] = 0
        return
    unit_list = configured_unit_list_price(series, line.get("selected_options") or [])
    discount = resolve_discount_pct(contract, series["category"], line["quantity"])
    unit_net = unit_net_price(unit_list, discount)
    line["unit_list_price_cents"] = unit_list
    line["unit_net_price_cents"] = unit_net
    line["line_total_cents"] = unit_net * line["quantity"]


def manufacturer_lead_days(series, selected_options) -> int:
    """Manufacturer-mode lead day count: STEELCASE sums option extra days,
    MILLERKNOLL takes the max (default 0)."""
    entries = selected_option_entries(series, selected_options)
    extras = [int(o.get("extra_lead_days", 0)) for o in entries]
    if series["manufacturer"] == "STEELCASE":
        extra = sum(extras)
    else:  # MILLERKNOLL
        extra = max(extras) if extras else 0
    return int(series["base_lead_time_days"]) + extra


def set_provisional_lead(line, series, submit_date):
    days = manufacturer_lead_days(series, line.get("selected_options") or [])
    line["provisional_lead_time_days"] = days
    line["provisional_promise_date"] = add_calendar_days(submit_date, days).isoformat()


def set_confirmed_lead(line, series, ack_date):
    """lead_time_confirmed: same day-count as provisional, re-anchored to the
    acknowledgment date and advanced in business days (Mon-Fri, starting the
    day after the acknowledgment date; holidays not modeled)."""
    days = manufacturer_lead_days(series, line.get("selected_options") or [])
    line["confirmed_lead_time_days"] = days
    line["confirmed_promise_date"] = add_business_days(ack_date, days).isoformat()


def install_event_labor_cost(event, order, contract, dealership) -> int:
    """install_event_labor_cost: rounded ONCE per event at completion."""
    rate = contract.get("labor_rate_cents_per_hour")
    if rate is None:
        rate = dealership["standard_labor_rate_cents_per_hour"]
    multiplier_bp = contract.get("after_hours_multiplier_bp")
    if multiplier_bp is None:
        multiplier_bp = dealership["after_hours_multiplier_bp"]
    ah_start = dealership["after_hours_start_minute"]
    total_minutes = event["end_minute"] - event["start_minute"]
    premium_minutes = max(0, event["end_minute"] - max(event["start_minute"], ah_start))
    standard_minutes = total_minutes - premium_minutes
    # (standard*rate + premium*rate*mult/10000) / 60, rounded half-up once
    numer = standard_minutes * rate * 10000 + premium_minutes * rate * multiplier_bp
    return round_half_up_int(numer, 600000)


def event_after_hours(event, dealership) -> bool:
    ah_start = dealership["after_hours_start_minute"]
    premium_minutes = max(0, event["end_minute"] - max(event["start_minute"], ah_start))
    return premium_minutes > 0


def restocking_fee(order_lines) -> int:
    """restocking_fee: applies on cancel from ACKNOWLEDGED."""
    unreceived_net = sum(
        l["line_total_cents"]
        for l in order_lines
        if l["status"] == "ACKNOWLEDGED" and l.get("received_units", 0) == 0
    )
    return max(MIN_RESTOCK_FEE_CENTS, round_half_up_int(unreceived_net * RESTOCK_PCT, 100))


def liquidation_estimate(item_count) -> int:
    """liquidation_credit_valuation, estimated variant: grade B with haircut."""
    per_item = EST_VALUE_PER_ITEM_CENTS[ESTIMATION_ASSUMED_GRADE]
    return round_half_up_int(item_count * per_item * (100 - ESTIMATION_HAIRCUT_PCT), 100)


def liquidation_final_credit(condition_grade, appraised_value_cents, item_count) -> int:
    """liquidation_credit_valuation, final variant: appraised value minus the
    15% liquidation fee minus per-item refurbishment, floored at 0."""
    fee_deducted = round_half_up_int(appraised_value_cents * (100 - LIQUIDATION_FEE_PCT), 100)
    refurb = REFURB_FEE_PER_ITEM_CENTS[condition_grade] * item_count
    return max(0, fee_deducted - refurb)


def appraisal_expired(appraised_at: str, current_date) -> bool:
    """A lot appraisal is valid for 30 days: EXPIRED when the current UTC date
    is more than thirty days after appraised_at."""
    from util import parse_date
    appraised = parse_date(appraised_at)
    if appraised is None:
        return False
    return current_date > appraised + timedelta(days=APPRAISAL_VALIDITY_DAYS)
