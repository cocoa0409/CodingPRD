"""Declared constants and the 31 calculation rules (PRD 2.6, 3.x)."""

from decimal import Decimal

from core import (
    D, add_days, ceil_int, days_between, floor_div_int, round_half_up,
    round_half_up_places,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PITCH_TIER_0_MAX_CENTS = D("5.0")
PITCH_TIER_1_MAX_CENTS = D("15.0")
PITCH_TIER_2_MAX_CENTS = D("35.0")
PITCH_TIERS = ("TIER_0", "TIER_1", "TIER_2", "TIER_3")
PITCH_TIER_OVERDUE_BUMP = 1
PITCH_RAISE_PASS_MINUTES = 35
PITCH_TIER_VISIT_COUNT = {"TIER_0": 1, "TIER_1": 1, "TIER_2": 1, "TIER_3": 2}
PITCH_DEVIATION_MIN_CENTS = -200.0
PITCH_DEVIATION_MAX_CENTS = 200.0
PITCH_HZ_MIN = 415.0
PITCH_HZ_MAX = 445.0

CYCLE_BASE_DAYS = {"HOME": 182, "STUDIO": 120, "INSTITUTIONAL": 91,
                   "PERFORMANCE": 45}
CLIMATE_CONTROLLED_MULTIPLIER = D("1.00")
CLIMATE_UNCONTROLLED_MULTIPLIER = D("0.75")
CLASS_CYCLE_ADJUST_DAYS = {"UPRIGHT": 0, "CONSOLE": 0, "BABY_GRAND": -7,
                           "GRAND": -14, "CONCERT_GRAND": -21}
MIN_CYCLE_INTERVAL_DAYS = 30
OVERDUE_T1_MAX_DAYS = 30
OVERDUE_T2_MAX_DAYS = 90
LAPSE_MIN_DAYS = 91

CLIMATE_LOOKBACK_WINDOW_DAYS = 180
CLIMATE_RH_BAND_MIN_PCT = D("35.0")
CLIMATE_RH_BAND_MAX_PCT = D("55.0")
CLIMATE_OUT_OF_BAND_RATIO_THRESHOLD = D("0.25")
CLIMATE_MIN_READINGS_FOR_EVALUATION = 4

SERVICE_BASE_MINUTES = {"TUNE": 60, "PITCH_RAISE": 35, "REGULATE": 240,
                        "VOICE": 150, "REBUILD": 2400}
CLASS_MINUTE_MULTIPLIER = {"UPRIGHT": D("1.00"), "CONSOLE": D("1.00"),
                           "BABY_GRAND": D("1.15"), "GRAND": D("1.30"),
                           "CONCERT_GRAND": D("1.60")}
SPLIT_VISIT_THRESHOLD_MINUTES = 300

SERVICE_BASE_PRICE_CENTS = {"TUNE": 19500, "PITCH_RAISE": 9500,
                            "REGULATE": 85000, "VOICE": 42000,
                            "REBUILD": 1450000}
CLASS_PRICE_MULTIPLIER = {"UPRIGHT": D("1.00"), "CONSOLE": D("1.05"),
                          "BABY_GRAND": D("1.20"), "GRAND": D("1.35"),
                          "CONCERT_GRAND": D("1.75")}
DEALER_NET_DISCOUNT_PCT = D("0.18")
INSTITUTIONAL_DISCOUNT_PCT = D("0.08")
RETAIL_DISCOUNT_PCT = D("0.00")
ZONE_SURCHARGE_CENTS = {"ZONE_A": 0, "ZONE_B": 4500, "ZONE_C": 11000}
LOYALTY_TIER_1_MIN_CENTS = 119250
LOYALTY_TIER_2_MIN_CENTS = 1450000
LOYALTY_TIER_1_PCT = D("0.03")
LOYALTY_TIER_2_PCT = D("0.06")
QUOTE_VALID_DAYS = 30

DEPOSIT_PCT = {"TUNE": D("0.00"), "PITCH_RAISE": D("0.00"),
               "REGULATE": D("0.25"), "VOICE": D("0.25"), "REBUILD": D("0.40")}
DEPOSIT_FLAT_MINIMUM_CENTS = 25000
DEPOSIT_NET_TERMS_PCT = D("0.10")
MILESTONE_COUNT = {"TUNE": 1, "PITCH_RAISE": 1, "REGULATE": 2, "VOICE": 2,
                   "REBUILD": 4}
MILESTONE_LABELS = {
    "REBUILD": ["DISASSEMBLY", "STRINGING", "ACTION_REGULATION", "FINAL_VOICING"],
    "REGULATE": ["ACTION_PREP", "FINAL_REGULATION"],
    "VOICE": ["HAMMER_PREP", "FINAL_VOICING"],
    "TUNE": ["COMPLETION"],
    "PITCH_RAISE": ["COMPLETION"],
}
MILESTONE_REJECTION_RETRY_LIMIT = 2

MOVE_BASE_CENTS = {"UPRIGHT": 28000, "CONSOLE": 32000, "BABY_GRAND": 52000,
                   "GRAND": 68000, "CONCERT_GRAND": 145000}
MOVE_STAIR_PER_FLIGHT_CENTS = 9000
MOVE_STAIR_BUNDLE_THRESHOLD_FLIGHTS = 4
MOVE_STAIR_BUNDLE_FLAT_CENTS = 25000
MOVE_CRANE_CENTS = 185000
MOVE_LOCAL_MAX_MILES = D("25.0")
MOVE_REGIONAL_MAX_MILES = D("150.0")
MOVE_LOCAL_FLAT_CENTS = 6000
MOVE_PER_MILE_CENTS = 420
MOVE_LONG_HAUL_FLAT_CENTS = 52000
MOVE_CLIMATE_TRANSPORT_CENTS = 38000
MOVE_CRANE_REQUIRED_MIN_FLIGHTS_CONCERT_GRAND = 2
MOVE_WINDOW_BUFFER_MINUTES = 90
MAX_STAIR_FLIGHTS_PER_LOCATION = 8

ROUTE_DAY_DEFAULT_CAPACITY_MINUTES = 480
TRAVEL_BUFFER_SAME_ZONE_MINUTES = 25
TRAVEL_BUFFER_CROSS_ZONE_MINUTES = 55
SAME_ADDRESS_CHAIN_BUFFER_MINUTES = 5
SAME_ADDRESS_DISCOUNT_PCT = D("0.20")
APPOINTMENT_MIN_LEAD_MINUTES = 120
ROUTE_DAY_LOCK_LEAD_HOURS = 12
RESCHEDULE_LIMIT = 2
RESCHEDULE_FREE_HOURS = D("48")
RESCHEDULE_FEE_CENTS = 7500
RESCHEDULE_DISPATCHED_FEE_CENTS = 20000
CANCEL_TIER_A_MIN_HOURS = D("72.0")
CANCEL_TIER_B_MIN_HOURS = D("24.0")
CANCEL_TIER_B_PCT = D("0.15")
CANCEL_TIER_C_PCT = D("0.35")
CANCEL_DISPATCHED_PCT = D("0.60")
CANCEL_DISPATCHED_MIN_CENTS = 15000

WARRANTY_TERM_DAYS = {"TUNE": 90, "PITCH_RAISE": 45, "REGULATE": 365,
                      "VOICE": 180, "REBUILD": 1095}
WARRANTY_CLAIM_LIMIT = 2
WARRANTY_PRORATION_THRESHOLD = D("0.50")
WARRANTY_TRANSFER_PRORATION_FLOOR_DAYS = 30

CONSIGNMENT_TERM_DAYS = 180
CONSIGNMENT_BASE_COMMISSION_PCT = D("0.25")
CONSIGNMENT_ABOVE_RESERVE_COMMISSION_PCT = D("0.15")
CONSIGNMENT_ABOVE_RESERVE_BONUS_PCT = D("0.50")
CONSIGNMENT_SALE_FLOOR_PCT = D("0.80")
CONSIGNMENT_MIN_RESERVE_CENTS = 50000

PARTS_REQ_QTY_HAMMER_SET = 1
PARTS_REQ_QTY_STRING_SET = 1
PARTS_REQ_QTY_ACTION_PARTS = {"UPRIGHT": 2, "CONSOLE": 2, "BABY_GRAND": 3,
                              "GRAND": 4, "CONCERT_GRAND": 6}
PARTIAL_ALLOCATION_MIN_PCT = D("0.50")
PARTS_MAX_REQUEST_QTY = 50

TECH_CERT_RANK = {"APPRENTICE": 1, "JOURNEYMAN": 2, "MASTER": 3}
SERVICE_MIN_CERT_RANK = {"TUNE": 1, "PITCH_RAISE": 2, "REGULATE": 2,
                         "VOICE": 2, "REBUILD": 3}

LEDGER_PRECEDENCE = ("REVERSAL", "WARRANTY_CREDIT", "CONSIGNMENT_PROCEEDS",
                     "DEPOSIT_REFUND", "CANCELLATION_FEE", "MILESTONE_CHARGE",
                     "DEPOSIT_CHARGE", "MANUAL_ADJUSTMENT")


# ---------------------------------------------------------------------------
# 1. pitch_tier_classification
# ---------------------------------------------------------------------------

def raw_pitch_tier(deviation):
    d = abs(D(deviation))
    if d <= PITCH_TIER_0_MAX_CENTS:
        return "TIER_0"
    if d <= PITCH_TIER_1_MAX_CENTS:
        return "TIER_1"
    if d <= PITCH_TIER_2_MAX_CENTS:
        return "TIER_2"
    return "TIER_3"


def bumped_tier(raw, governing_recall):
    bump = 0
    if governing_recall is not None and governing_recall.get("overdue_tier") in (
            "OVERDUE_T2", "LAPSED_TIER"):
        bump = PITCH_TIER_OVERDUE_BUMP
    idx = min(3, PITCH_TIERS.index(raw) + bump)
    return PITCH_TIERS[idx]


def planned_visits(effective_tier):
    return PITCH_TIER_VISIT_COUNT[effective_tier]


# ---------------------------------------------------------------------------
# 2. tuning_cycle_interval  /  3. recall_due_date  /  4. recall_overdue_tier
# ---------------------------------------------------------------------------

def tuning_cycle_interval(usage_tier, climate_controlled, instrument_class):
    base = CYCLE_BASE_DAYS[usage_tier]
    mult = (CLIMATE_CONTROLLED_MULTIPLIER if climate_controlled
            else CLIMATE_UNCONTROLLED_MULTIPLIER)
    floored = floor_div_int(D(base) * mult)
    adj = CLASS_CYCLE_ADJUST_DAYS[instrument_class]
    return max(MIN_CYCLE_INTERVAL_DAYS, floored + adj)


def recall_due_date(cycle_start, interval_days):
    return add_days(cycle_start, interval_days)


def overdue_tier_for(days_overdue):
    if days_overdue == 0:
        return "ON_TIME"
    if days_overdue <= OVERDUE_T1_MAX_DAYS:
        return "OVERDUE_T1"
    if days_overdue <= OVERDUE_T2_MAX_DAYS:
        return "OVERDUE_T2"
    return "LAPSED_TIER"


def days_overdue_for(clock_date, due_date):
    return max(0, days_between(clock_date, due_date))


# ---------------------------------------------------------------------------
# 5. quote_line_composition  /  6. quote_pricing  /  7. loyalty  /  8. deposit
# ---------------------------------------------------------------------------

def quote_lines(service_type, effective_tier):
    if service_type == "TUNE" and effective_tier in ("TIER_1", "TIER_2", "TIER_3"):
        return ["TUNE", "PITCH_RAISE"]
    return [service_type]


def pricing_variant_for(client_type):
    if client_type == "DEALER":
        return "DEALER_NET", DEALER_NET_DISCOUNT_PCT
    if client_type == "INSTITUTION":
        return "INSTITUTIONAL", INSTITUTIONAL_DISCOUNT_PCT
    return "RETAIL", RETAIL_DISCOUNT_PCT


def loyalty_discount(subtotal_cents):
    if subtotal_cents >= LOYALTY_TIER_2_MIN_CENTS:
        pct = LOYALTY_TIER_2_PCT
    elif subtotal_cents >= LOYALTY_TIER_1_MIN_CENTS:
        pct = LOYALTY_TIER_1_PCT
    else:
        pct = D("0.00")
    return round_half_up(D(subtotal_cents) * pct)


def quote_pricing(service_type, instrument_class, effective_tier, client_type,
                  zone_code):
    lines = quote_lines(service_type, effective_tier)
    mult = CLASS_PRICE_MULTIPLIER[instrument_class]
    line_bases = [round_half_up(D(SERVICE_BASE_PRICE_CENTS[l]) * mult)
                  for l in lines]
    base_price_cents = sum(line_bases)
    variant, pct = pricing_variant_for(client_type)
    line_nets = [round_half_up(D(b) * (D(1) - pct)) for b in line_bases]
    net_sum = sum(line_nets)
    line_discount_cents = base_price_cents - net_sum
    zone_surcharge_cents = ZONE_SURCHARGE_CENTS[zone_code]
    subtotal_cents = net_sum + zone_surcharge_cents
    loyalty_cents = loyalty_discount(subtotal_cents)
    total_cents = subtotal_cents - loyalty_cents
    return {
        "line_count": len(lines),
        "base_price_cents": base_price_cents,
        "line_discount_cents": line_discount_cents,
        "zone_surcharge_cents": zone_surcharge_cents,
        "subtotal_cents": subtotal_cents,
        "loyalty_discount_cents": loyalty_cents,
        "total_cents": total_cents,
        "pricing_variant": variant,
    }


def deposit_required(total_cents, service_type, client_type):
    pct = DEPOSIT_PCT[service_type]
    if pct == D("0.00"):
        return 0, "PERCENT_OF_CONTRACT"
    if client_type == "INSTITUTION":
        return round_half_up(D(total_cents) * DEPOSIT_NET_TERMS_PCT), "NET_TERMS"
    raw = round_half_up(D(total_cents) * pct)
    if raw >= DEPOSIT_FLAT_MINIMUM_CENTS:
        return raw, "PERCENT_OF_CONTRACT"
    return DEPOSIT_FLAT_MINIMUM_CENTS, "FLAT_MINIMUM"


# ---------------------------------------------------------------------------
# 9. milestone_waterfall  /  10. service_order_duration
# ---------------------------------------------------------------------------

def milestone_schedule(service_type, contract_total_cents):
    n = MILESTONE_COUNT[service_type]
    labels = MILESTONE_LABELS[service_type]
    share = floor_div_int(D(contract_total_cents) / D(n))
    out = []
    for i in range(1, n + 1):
        amount = share if i < n else contract_total_cents - share * (n - 1)
        out.append({"sequence_index": i, "label": labels[i - 1],
                    "amount_cents": amount})
    return out


def service_order_duration(service_type, instrument_class, effective_tier):
    base = round_half_up(D(SERVICE_BASE_MINUTES[service_type]) *
                         CLASS_MINUTE_MULTIPLIER[instrument_class])
    if service_type == "TUNE" and effective_tier in ("TIER_1", "TIER_2", "TIER_3"):
        base += PITCH_RAISE_PASS_MINUTES
    if base > SPLIT_VISIT_THRESHOLD_MINUTES:
        return base + PITCH_RAISE_PASS_MINUTES, "SPLIT_VISIT"
    return base, "SINGLE_VISIT"


# ---------------------------------------------------------------------------
# 11..13 appointment minutes / buffer / estimated price
# ---------------------------------------------------------------------------

def appointment_service_minutes(service_type, instrument_class, effective_tier):
    minutes = round_half_up(D(SERVICE_BASE_MINUTES[service_type]) *
                            CLASS_MINUTE_MULTIPLIER[instrument_class])
    if service_type == "TUNE" and effective_tier in ("TIER_1", "TIER_2", "TIER_3"):
        minutes += PITCH_RAISE_PASS_MINUTES
    return minutes


def appointment_travel_buffer(chained, zone_code, tech_zones):
    if chained:
        return SAME_ADDRESS_CHAIN_BUFFER_MINUTES
    if zone_code in tech_zones:
        return TRAVEL_BUFFER_SAME_ZONE_MINUTES
    return TRAVEL_BUFFER_CROSS_ZONE_MINUTES


def appointment_estimated_price(service_type, instrument_class, effective_tier,
                                chained):
    mult = CLASS_PRICE_MULTIPLIER[instrument_class]
    list_price = round_half_up(D(SERVICE_BASE_PRICE_CENTS[service_type]) * mult)
    if service_type == "TUNE" and effective_tier in ("TIER_1", "TIER_2", "TIER_3"):
        list_price += round_half_up(D(SERVICE_BASE_PRICE_CENTS["PITCH_RAISE"]) * mult)
    if chained:
        return list_price - round_half_up(D(list_price) * SAME_ADDRESS_DISCOUNT_PCT)
    return list_price


# ---------------------------------------------------------------------------
# 14. move components
# ---------------------------------------------------------------------------

def effective_flights(location):
    if location.get("has_service_elevator"):
        return 0
    return location.get("stair_flights") or 0


def move_stair_component(origin, destination):
    total = effective_flights(origin) + effective_flights(destination)
    if total >= MOVE_STAIR_BUNDLE_THRESHOLD_FLIGHTS:
        return total, MOVE_STAIR_BUNDLE_FLAT_CENTS
    return total, total * MOVE_STAIR_PER_FLIGHT_CENTS


def move_distance_component(distance_miles):
    miles = D(distance_miles)
    if miles <= MOVE_LOCAL_MAX_MILES:
        return "LOCAL", "FLAT_LOCAL", MOVE_LOCAL_FLAT_CENTS
    if miles <= MOVE_REGIONAL_MAX_MILES:
        return "REGIONAL", "PER_MILE", round_half_up(miles * D(MOVE_PER_MILE_CENTS))
    return "LONG_HAUL", "LONG_HAUL_FLAT", MOVE_LONG_HAUL_FLAT_CENTS


# ---------------------------------------------------------------------------
# 15. cancellation_fee  /  16. reschedule_fee
# ---------------------------------------------------------------------------

def cancellation_fee(estimated_price_cents, fulfillment_status, lead_hours):
    if fulfillment_status in ("EN_ROUTE", "IN_PROGRESS"):
        fee = max(round_half_up(D(estimated_price_cents) * CANCEL_DISPATCHED_PCT),
                  CANCEL_DISPATCHED_MIN_CENTS)
        return fee, "DISPATCHED_TIER"
    if lead_hours >= CANCEL_TIER_A_MIN_HOURS:
        return 0, "LEAD_TIME_TIER"
    if lead_hours >= CANCEL_TIER_B_MIN_HOURS:
        return round_half_up(D(estimated_price_cents) * CANCEL_TIER_B_PCT), \
            "LEAD_TIME_TIER"
    return round_half_up(D(estimated_price_cents) * CANCEL_TIER_C_PCT), \
        "LEAD_TIME_TIER"


def reschedule_fee(fulfillment_status, lead_hours):
    if fulfillment_status in ("EN_ROUTE", "IN_PROGRESS"):
        return RESCHEDULE_DISPATCHED_FEE_CENTS
    if lead_hours >= RESCHEDULE_FREE_HOURS:
        return 0
    return RESCHEDULE_FEE_CENTS


# ---------------------------------------------------------------------------
# 17. climate evaluation
# ---------------------------------------------------------------------------

def reading_in_band(rh_pct):
    return CLIMATE_RH_BAND_MIN_PCT <= D(rh_pct) <= CLIMATE_RH_BAND_MAX_PCT


def climate_evaluation(readings_rh):
    """readings_rh: relative_humidity_pct values inside the closed window."""
    n = len(readings_rh)
    out_count = sum(1 for rh in readings_rh if not reading_in_band(rh))
    if n < CLIMATE_MIN_READINGS_FOR_EVALUATION:
        flag = False
    else:
        flag = (D(out_count) / D(n)) > CLIMATE_OUT_OF_BAND_RATIO_THRESHOLD
    return n, out_count, flag


# ---------------------------------------------------------------------------
# 18..20 warranty term / claim resolution / transfer term
# ---------------------------------------------------------------------------

def warranty_term(service_type):
    return WARRANTY_TERM_DAYS[service_type]


def warranty_claim_resolution(covered_price_cents, term_days, start_date,
                              clock_date):
    days_elapsed = days_between(clock_date, start_date)
    raw = D(days_elapsed) / D(term_days)
    clamped = min(D(1), max(D(0), raw))
    fraction = round_half_up_places(clamped, 4)
    if fraction < WARRANTY_PRORATION_THRESHOLD:
        return float(fraction), "FREE_RESERVICE", 0
    credit = round_half_up(D(covered_price_cents) * (D(1) - fraction))
    return float(fraction), "PRORATED_CREDIT", credit


def warranty_transfer_term(term_days, start_date, sale_date):
    days_elapsed = days_between(sale_date, start_date)
    remaining = term_days - days_elapsed
    return max(WARRANTY_TRANSFER_PRORATION_FLOOR_DAYS, remaining)


# ---------------------------------------------------------------------------
# 21..22 consignment split / sale floor
# ---------------------------------------------------------------------------

def consignment_sale_floor(reserve_price_cents):
    return round_half_up(D(reserve_price_cents) * CONSIGNMENT_SALE_FLOOR_PCT)


def consignment_proceeds_split(advanced_restoration_cents, reserve_price_cents,
                               sale_price_cents):
    advance_recovered = min(advanced_restoration_cents, sale_price_cents)
    residual = sale_price_cents - advance_recovered
    if sale_price_cents <= reserve_price_cents:
        variant = "AT_OR_BELOW_RESERVE"
        commission = round_half_up(D(residual) * CONSIGNMENT_BASE_COMMISSION_PCT)
    else:
        variant = "ABOVE_RESERVE"
        excess = sale_price_cents - reserve_price_cents
        reserve_part = max(0, residual - excess)
        excess_part = residual - reserve_part
        commission = (
            round_half_up(D(reserve_part) * CONSIGNMENT_ABOVE_RESERVE_COMMISSION_PCT)
            + round_half_up(D(excess_part) * CONSIGNMENT_ABOVE_RESERVE_BONUS_PCT)
        )
    payout = residual - commission
    shop = sale_price_cents - advance_recovered - payout
    return {
        "split_variant": variant,
        "advance_recovered_cents": advance_recovered,
        "consignor_payout_cents": payout,
        "shop_commission_cents": shop,
    }


# ---------------------------------------------------------------------------
# 23..25 parts
# ---------------------------------------------------------------------------

def parts_requirement(instrument_class):
    return {
        "HAMMER_SET": PARTS_REQ_QTY_HAMMER_SET,
        "STRING_SET": PARTS_REQ_QTY_STRING_SET,
        "ACTION_PARTS": PARTS_REQ_QTY_ACTION_PARTS[instrument_class],
    }


def partial_floor(requested_qty):
    return ceil_int(D(requested_qty) * PARTIAL_ALLOCATION_MIN_PCT)


# ---------------------------------------------------------------------------
# 26. technician certification gate
# ---------------------------------------------------------------------------

def cert_ok(certification_level, service_type):
    return TECH_CERT_RANK[certification_level] >= SERVICE_MIN_CERT_RANK[service_type]
