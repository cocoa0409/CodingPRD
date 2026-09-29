"""Calculation rules (SCAFFOLD §1.3 / PRD §3)."""

from datetime import timedelta
from decimal import Decimal

from db import db
from errors import ApiError
from util import ceil_int, dec, floor_int, parse_dt, rhu, rhu_int, two_dp

# ---- constants -----------------------------------------------------------
EARLY_FILING_DISCOUNT_PCT = Decimal("0.015")
EARLY_FILING_WINDOW_DAYS = 20
RESERVE_AMORTIZATION_YEARS = 2
SURCHARGE_TIER_LOW_MAX_CENTS = 800
SURCHARGE_TIER_MID_MAX_CENTS = 1600
SURCHARGE_PCT_LOW_TIER = Decimal("0.06")
SURCHARGE_PCT_MID_TIER = Decimal("0.04")
SURCHARGE_PCT_HIGH_TIER = Decimal("0.02")
BAND_LOW_MULTIPLIER = Decimal("0.80")
BAND_HIGH_MULTIPLIER = Decimal("1.20")
RATE_INCREASE_COVERAGE_CEILING_MONTHS = Decimal("3.00")
VOLUME_BONUS_PCT = Decimal("0.05")
TURNAROUND_BUFFER_MINUTES = 60
STOP_FEE_CENTS = 2500
MIN_ROUTE_PAYMENT_CENTS = 4000
REJECT_HANDLING_CENTS = 300
MAX_CONTAMINATION_PCT = Decimal("5.00")
MAX_CONTAMINATION_STRIKES = 3
INFESTATION_QUARANTINE_DAYS = 14
AVG_UNIT_WEIGHT_KG = Decimal("28.0")
MIN_RECERTIFICATION_DIVERSION_PCT = Decimal("75.00")
TAKEBACK_BREACH_PENALTY_CENTS = 2500
REGISTRANT_SUSPENSION_BALANCE_CENTS = 1000000

LINE_ORDER = ("FOUNDATION", "MATTRESS")
LEDGER_REMITTANCE_STATUSES = (
    "PAID", "UNDER_AUDIT", "AMENDMENT_REQUIRED", "AUDIT_CLOSED", "REFUNDED",
)
ACTIVE_ROUTE_STATUSES = ("SCHEDULED", "PICKED_UP", "DELIVERED")


# --------------------------------------------------------------------------
# calculations.fee_rate_recommendation  (PRD §3.1)
# --------------------------------------------------------------------------
def fee_rate_recommendation(program):
    cost = program["forecast_annual_cost_cents"]
    months = program["reserve_target_months"]
    units = program["forecast_annual_units"]
    other = program["forecast_other_revenue_cents"]
    reserve_balance = program.get("reserve_balance_cents", 0)

    reserve_target_cents = rhu_int(dec(cost) * dec(months) / Decimal(12))
    reserve_gap_cents = max(0, reserve_target_cents - reserve_balance)
    recoverable_cents = (cost
                         + rhu_int(dec(reserve_gap_cents) / Decimal(RESERVE_AMORTIZATION_YEARS))
                         - other)
    base_rate_cents = ceil_int(dec(recoverable_cents) / dec(units))
    if base_rate_cents <= SURCHARGE_TIER_LOW_MAX_CENTS:
        surcharge = SURCHARGE_PCT_LOW_TIER
    elif base_rate_cents <= SURCHARGE_TIER_MID_MAX_CENTS:
        surcharge = SURCHARGE_PCT_MID_TIER
    else:
        surcharge = SURCHARGE_PCT_HIGH_TIER
    recommended = base_rate_cents + rhu_int(dec(base_rate_cents) * surcharge)
    band_low = floor_int(dec(recommended) * BAND_LOW_MULTIPLIER)
    band_high = ceil_int(dec(recommended) * BAND_HIGH_MULTIPLIER)
    return {
        "reserve_target_cents": reserve_target_cents,
        "reserve_gap_cents": reserve_gap_cents,
        "recoverable_cents": recoverable_cents,
        "base_rate_cents": base_rate_cents,
        "admin_surcharge_pct": float(surcharge),
        "recommended_rate_cents": recommended,
        "band_low_cents": band_low,
        "band_high_cents": band_high,
    }


# --------------------------------------------------------------------------
# calculations.reserve_coverage_months  (PRD §3.1)
# --------------------------------------------------------------------------
def reserve_coverage_months_decimal(program):
    monthly = rhu_int(dec(program["forecast_annual_cost_cents"]) / Decimal(12))
    if monthly == 0:
        return Decimal("0.00")
    return rhu(dec(program.get("reserve_balance_cents", 0)) / dec(monthly), 2)


def coverage_decimal_of(program):
    """The stored two-decimal coverage figure, as a Decimal for gate compares."""
    return dec(program.get("reserve_coverage_months", 0))


# --------------------------------------------------------------------------
# calculations.applicable_rate_lookup  (PRD §3.2)
# --------------------------------------------------------------------------
def applicable_rate(program_id, unit_class, as_of_dt):
    candidates = []
    for sched in db.fee_rate_schedules.values():
        if sched["state_program_id"] != program_id:
            continue
        if sched["unit_class"] != unit_class:
            continue
        if sched["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        eff_from = parse_dt(sched["effective_from"])
        if eff_from > as_of_dt:
            continue
        if sched["effective_to"] is not None:
            if not as_of_dt < parse_dt(sched["effective_to"]):
                continue
        candidates.append(sched)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (parse_dt(s["effective_from"]), s["created_at"], s["_seq"]),
                    reverse=True)
    return candidates[0]["fee_cents_per_unit"]


# --------------------------------------------------------------------------
# calculations.rate_period_overlap  (PRD §3.2)
# --------------------------------------------------------------------------
def rate_period_overlaps(program_id, unit_class, new_from, new_to):
    for sched in db.fee_rate_schedules.values():
        if sched["state_program_id"] != program_id:
            continue
        if sched["unit_class"] != unit_class:
            continue
        if sched["status"] not in ("PROPOSED", "APPROVED", "ACTIVE"):
            continue
        exist_from = parse_dt(sched["effective_from"])
        exist_to = parse_dt(sched["effective_to"]) if sched["effective_to"] else None
        # half-open intervals; a null bound is +infinity
        cond_a = True if exist_to is None else new_from < exist_to
        cond_b = True if new_to is None else exist_from < new_to
        if cond_a and cond_b:
            return True
    return False


# --------------------------------------------------------------------------
# calculations.remittance_fee_assessment  (PRD §3.3 / §3.4)
# --------------------------------------------------------------------------
def claims_of(remittance_id):
    return [c for c in db.exemption_claims.values()
            if c["remittance_id"] == remittance_id]


def is_early_filing(filed_at_dt, period_end_dt):
    return filed_at_dt <= period_end_dt + timedelta(days=EARLY_FILING_WINDOW_DAYS)


def remittance_fee_assessment(remittance, variant):
    """variant is SELF_ASSESSED or AUDIT_RECONCILED."""
    program_id = remittance["state_program_id"]
    period_start = parse_dt(remittance["period_start"])
    period_end = parse_dt(remittance["period_end"])
    claims = claims_of(remittance["id"])

    if variant == "SELF_ASSESSED":
        rate_date = period_start
        inclusion = ("PENDING", "SUBSTANTIATED")
        forfeited = False
    else:
        rate_date = period_end
        inclusion = ("SUBSTANTIATED",)
        forfeited = any(c["status"] == "DISALLOWED" for c in claims)

    early = bool(remittance.get("early_filing_qualified"))
    if remittance.get("filed_at"):
        early = is_early_filing(parse_dt(remittance["filed_at"]), period_end)

    discount_pct = EARLY_FILING_DISCOUNT_PCT if (early and not forfeited) else Decimal(0)

    fee = 0
    for unit_class in LINE_ORDER:
        units_sold = (remittance["units_sold_foundation"] if unit_class == "FOUNDATION"
                      else remittance["units_sold_mattress"])
        if units_sold <= 0:
            continue
        credited_exempt = sum(c["units"] for c in claims
                              if c["unit_class"] == unit_class and c["status"] in inclusion)
        chargeable = max(0, units_sold - credited_exempt)
        rate = applicable_rate(program_id, unit_class, rate_date)
        if rate is None:
            raise ApiError("ERR_NO_APPLICABLE_RATE")
        gross_cents = chargeable * rate
        discount_cents = rhu_int(dec(gross_cents) * discount_pct)
        fee += gross_cents - discount_cents
    return fee


def remittance_rate_available(remittance):
    """Filing gate: a rate must cover period_start AND period_end per class."""
    program_id = remittance["state_program_id"]
    period_start = parse_dt(remittance["period_start"])
    period_end = parse_dt(remittance["period_end"])
    for unit_class in LINE_ORDER:
        units_sold = (remittance["units_sold_foundation"] if unit_class == "FOUNDATION"
                      else remittance["units_sold_mattress"])
        if units_sold <= 0:
            continue
        for as_of in (period_start, period_end):
            if applicable_rate(program_id, unit_class, as_of) is None:
                return False
    return True


# --------------------------------------------------------------------------
# calculations.site_volume_credit  (PRD §3.5)
# --------------------------------------------------------------------------
def site_volume_credit(program, units_mattress, units_foundation):
    credited_units = units_mattress + units_foundation
    bonus = (VOLUME_BONUS_PCT
             if credited_units >= program["volume_bonus_threshold_units"] else Decimal(0))
    credit = rhu_int(dec(credited_units) * dec(program["site_credit_cents_per_unit"])
                     * (Decimal(1) + bonus))
    return credited_units, credit


# --------------------------------------------------------------------------
# calculations.hauler_window_conflict / hauler_selection  (PRD §3.6)
# --------------------------------------------------------------------------
def conflicting_route_count(hauler_id, window_start, window_end):
    padded_start = window_start - timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    padded_end = window_end + timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    count = 0
    for order in db.pickup_orders.values():
        if order["hauler_id"] != hauler_id:
            continue
        if order["fulfillment_status"] not in ACTIVE_ROUTE_STATUSES:
            continue
        exist_start = parse_dt(order["pickup_window_start"])
        exist_end = parse_dt(order["pickup_window_end"])
        if padded_start <= exist_end and exist_start <= padded_end:
            count += 1
    return count


def eligible_haulers(site, window_start, window_end):
    pool = []
    for hauler in db.haulers.values():
        if hauler["state_program_id"] != site["state_program_id"]:
            continue
        if site["region_code"] not in hauler["service_regions"]:
            continue
        if conflicting_route_count(hauler["id"], window_start, window_end) >= \
                hauler["max_concurrent_routes"]:
            continue
        pool.append(hauler)
    pool.sort(key=lambda h: (h["per_unit_rate_cents"], h["active_route_count"],
                             h["created_at"], h["_seq"]))
    return pool


# --------------------------------------------------------------------------
# calculations.hauler_route_payment  (PRD §3.6 / §3.7)
# --------------------------------------------------------------------------
def hauler_route_payment(order, hauler, billable_units, rejected_units):
    distance_cents = rhu_int(dec(order["route_distance_km"]) * dec(hauler["per_km_rate_cents"]))
    raw_cents = billable_units * hauler["per_unit_rate_cents"] + distance_cents + STOP_FEE_CENTS
    capped_cents = min(raw_cents, hauler["max_route_payment_cents"])
    floored_cents = max(capped_cents, MIN_ROUTE_PAYMENT_CENTS)
    handling_cents = rejected_units * REJECT_HANDLING_CENTS
    return max(0, floored_cents - handling_cents)


# --------------------------------------------------------------------------
# calculations.load_inspection_disposition  (PRD §3.7)
# --------------------------------------------------------------------------
def load_inspection_disposition(units_delivered, contaminated_unit_count, infestation_finding):
    if units_delivered and units_delivered > 0:
        pct = rhu(dec(contaminated_unit_count) / dec(units_delivered) * Decimal(100), 2)
    else:
        pct = Decimal("0.00")
    if infestation_finding != "NONE":
        return float(pct), "FULL_REJECT", 0, "INFESTATION"
    if pct > MAX_CONTAMINATION_PCT:
        return float(pct), "FULL_REJECT", 0, "CONTAMINATION_THRESHOLD"
    return float(pct), "PARTIAL_ACCEPT", units_delivered - contaminated_unit_count, None


# --------------------------------------------------------------------------
# calculations.recycler_diversion_rate  (PRD §3.7)
# --------------------------------------------------------------------------
def recycler_diversion_rate(verified_weight_kg, units_processed_count):
    basis = dec(units_processed_count) * AVG_UNIT_WEIGHT_KG
    if basis == 0:
        return 0.0
    return two_dp(dec(verified_weight_kg) / basis * Decimal(100))
