"""Pricing calculations per SCAFFOLD §1.3 / PRD §3.3, §3.6, §2.8."""
from decimal import Decimal, ROUND_HALF_UP

import db

# Constants
BASE_CENTS = {
    "MEET_ARRIVAL": 6000,
    "DEPARTURE_ESCORT": 7500,
    "CONNECTION_TRANSFER": 9500,
}
TIER_MULT_BP = {
    "STANDARD": 10000,
    "PRIORITY": 12500,
    "CONCIERGE": 15000,
}
POSTURE_MULT_BP = {
    "NORMAL": 10000,
    "DEGRADED": 12500,
}
COMPANION_FEE_CENTS = 1500
WCHR_FEE_CENTS = 800
WCHC_FEE_CENTS = 1800
UMNR_FEE_CENTS = 2500
SENIOR_FEE_CENTS = 900
TSA_ESCORT_FEE_CENTS = 1200
GRACE_MINUTES = 20
DELAY_PER_MIN_CENTS = 75
MAINT_INTERVAL = 50

# Estimated transfer minutes by leg_kind
ESTIMATED_TRANSFER_MINUTES = {
    "MEET_ARRIVAL": 45,
    "DEPARTURE_ESCORT": 60,
    "CONNECTION_TRANSFER": 75,
}


def _round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _leg_flat_fees_cents(leg: dict, request: dict) -> int:
    fees = 0
    fees += request.get("companion_count", 0) * COMPANION_FEE_CENTS
    if leg.get("requires_wchc_chair"):
        fees += WCHC_FEE_CENTS
    elif leg.get("requires_wheelchair"):
        fees += WCHR_FEE_CENTS
    if leg.get("requires_ummr_agent"):
        fees += UMNR_FEE_CENTS
    if leg.get("requires_senior_agent"):
        fees += SENIOR_FEE_CENTS
    if leg.get("requires_tsa_escort"):
        fees += TSA_ESCORT_FEE_CENTS
    return fees


def provisional_leg_charge(leg: dict, request: dict, airport: dict) -> int:
    """Forward-looking charge: base + fees, tier mult, posture mult, round half-up."""
    base = BASE_CENTS[leg["leg_kind"]] + _leg_flat_fees_cents(leg, request)
    tier_bp = TIER_MULT_BP[request["service_tier"]]
    posture_bp = POSTURE_MULT_BP.get(airport["posture"], 10000)
    val = (Decimal(base) * Decimal(tier_bp) / Decimal(10000)
           * Decimal(posture_bp) / Decimal(10000))
    return _round_half_up_cents(val)


def final_leg_charge(leg: dict, request: dict, airport: dict, segment: dict,
                     force_normal_posture: bool = False) -> int:
    """Chronological charge at COMPLETED: same base, posture at completion, plus delay surcharge."""
    base = BASE_CENTS[leg["leg_kind"]] + _leg_flat_fees_cents(leg, request)
    tier_bp = TIER_MULT_BP[request["service_tier"]]
    if force_normal_posture:
        posture_bp = 10000
    else:
        posture_bp = POSTURE_MULT_BP.get(airport["posture"], 10000)
    val = (Decimal(base) * Decimal(tier_bp) / Decimal(10000)
           * Decimal(posture_bp) / Decimal(10000))
    rounded = _round_half_up_cents(val)

    # Delay surcharge appended AFTER rounding.
    delay_min = 0
    actual = segment.get("actual_utc")
    scheduled = segment.get("scheduled_utc")
    if actual and scheduled:
        delta_seconds = (actual - scheduled).total_seconds()
        if delta_seconds > 0:
            delay_min = int(delta_seconds // 60)
    surcharge = max(0, delay_min - GRACE_MINUTES) * DELAY_PER_MIN_CENTS
    return rounded + surcharge


NON_TERMINAL_LEG_STATUSES = {"PLANNED", "DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE", "HANDED_OFF"}


def request_provisional_total(request_id: str) -> int:
    total = 0
    for leg in db.legs.values():
        if leg["assist_request_id"] != request_id:
            continue
        if leg["status"] not in NON_TERMINAL_LEG_STATUSES:
            continue
        total += leg.get("provisional_leg_cents") or 0
    return total


def request_final_total(request_id: str) -> int:
    total = 0
    for leg in db.legs.values():
        if leg["assist_request_id"] != request_id:
            continue
        if leg["status"] == "CANCELLED":
            continue
        total += leg.get("final_leg_cents") or 0
    return total


def recompute_provisional_for_request(request_id: str) -> None:
    """Recompute each non-terminal leg's provisional charge and the request total."""
    request = db.assist_requests[request_id]
    for leg in db.legs.values():
        if leg["assist_request_id"] != request_id:
            continue
        if leg["status"] not in NON_TERMINAL_LEG_STATUSES:
            continue
        segment = db.segments[leg["segment_id"]]
        airport = db.airports[segment["airport_id"]]
        leg["provisional_leg_cents"] = provisional_leg_charge(leg, request, airport)
        db.touch(leg)
    request["provisional_charge_cents"] = request_provisional_total(request_id)
