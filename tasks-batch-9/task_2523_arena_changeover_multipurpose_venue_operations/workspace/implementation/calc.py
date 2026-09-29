"""Every calculation rule and domain constant (PRD 3.x)."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from store import db, now_logical

# --- constants -------------------------------------------------------------
VENUE_LOCAL_UTC_OFFSET_HOURS = -4
OVERNIGHT_END_LOCAL_HOUR = 6

HOLD_WINDOW_HOURS = {"TIER_1": 336, "TIER_2": 168, "TIER_3": 72, "OPEN": 24}
TIER_RANK = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3, "OPEN": 4}
CHALLENGE_CREDIT_GRANT = 2

ICE_COVER_MINUTES = 90
ICE_UNCOVER_MINUTES = 75
ICE_MELT_MINUTES = 600
ICE_BUILD_MINUTES = 720
SEATING_MODE_MINUTES = {"FULL_BOWL": 0, "RETRACTABLE_IN": 120, "CURTAINED_HALF": 180}
PANELS_PER_SET = 40
PANEL_SET_MINUTES = 15
CREW_FACTOR_MIN = Fraction(1, 2)
CREW_FACTOR_MAX = Fraction(2, 1)
OVERNIGHT_SLOWDOWN = Fraction(115, 100)

LABOR_BASE_RATE_CENTS_PER_HOUR = {
    "STAGEHAND": 4800,
    "RIGGER": 7200,
    "ICE_TECH": 5600,
    "ELECTRICIAN": 6900,
    "CONVERSION_CREW": 4200,
}
OT_THRESHOLD_HOURS = Decimal(8)
OT_MULTIPLIER = Decimal("1.5")
OVERNIGHT_RATE_MULTIPLIER = Decimal("1.35")

CANCEL_FREE_NOTICE_HOURS = Decimal(48)
CANCEL_PARTIAL_NOTICE_HOURS = Decimal(12)
CANCEL_PARTIAL_FACTOR = Decimal("0.25")
CANCEL_LATE_FACTOR = Decimal("0.50")

DISPLACEMENT_BASE_CENTS = {"TIER_2": 650000, "TIER_3": 250000, "OPEN": 120000}
NOTICE_LONG_DAYS = 90
NOTICE_MID_DAYS = 30
ADMIN_HIGH_SUBTOTAL_CENTS = 400000
ADMIN_MID_SUBTOTAL_CENTS = 150000

W_DEHUM = Decimal("0.45")
W_COVER = Decimal("0.30")
W_THICKNESS = Decimal("0.25")
COVER_HOURS_LIMIT = Decimal(72)
NOMINAL_THICKNESS_MM = Decimal(32)
CONDENSATION_BLOCK_THRESHOLD = Decimal("40.00")
MIN_DEHUM_FRACTION = Decimal("0.25")
COVER_CYCLE_LIMIT = 3

CHANGEOVER_DEBT_FREEZE_MINUTES = 180

FLOOR_STAGES = ("NOT_STARTED", "STRIKING", "LAYING", "FLOOR_COMPLETE")
SEATING_STAGES = ("NOT_STARTED", "RETRACTING", "CURTAINING", "SEATING_COMPLETE")
INFRA_STAGES = ("NOT_STARTED", "UTILITY_SET", "NETWORK_SET", "BROADCAST_READY")
DIMENSIONS = {
    "FLOOR": ("floor_stage", FLOOR_STAGES),
    "SEATING": ("seating_stage", SEATING_STAGES),
    "INFRA": ("infra_stage", INFRA_STAGES),
}
ALL_STAGES = tuple(sorted(set(FLOOR_STAGES + SEATING_STAGES + INFRA_STAGES)))

LIVE_BOOKING_STATES = ("HELD", "CHALLENGED", "CONFIRMED")
TERMINAL_ORDER_STATES = ("SIGNED_OFF", "ABANDONED")


# --- numeric helpers -------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def as_number(value):
    """Render a Decimal for JSON: an integral value becomes int, else float."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def ceil_div(numerator, denominator):
    return -(-int(numerator) // int(denominator))


# --- overnight_shift_flag --------------------------------------------------
def overnight_shift_flag(instant, venue):
    local = instant + timedelta(hours=VENUE_LOCAL_UTC_OFFSET_HOURS)
    hour = local.hour
    return bool(hour >= int(venue["overnight_shift_start_local_hour"])
                or hour < OVERNIGHT_END_LOCAL_HOUR)


# --- hold_expires_at -------------------------------------------------------
def hold_expires_at(hold_placed_at, tier):
    return hold_placed_at + timedelta(hours=HOLD_WINDOW_HOURS[tier])


# --- hold_priority_delta ---------------------------------------------------
def priority_delta(incumbent_hold_tier, challenger_tier):
    return TIER_RANK[incumbent_hold_tier] - TIER_RANK[challenger_tier]


# --- changeover_turnaround_minutes ----------------------------------------
def planned_turnaround_minutes(from_profile, to_profile, venue_ice_deck_status,
                               crew_headcount, overnight):
    if from_profile["requires_ice"] and not to_profile["requires_ice"]:
        ice_adder = ICE_COVER_MINUTES if to_profile["ice_cover_required"] else ICE_MELT_MINUTES
    elif (not from_profile["requires_ice"]) and to_profile["requires_ice"]:
        if venue_ice_deck_status in ("IN_SERVICE", "COVERED"):
            ice_adder = ICE_UNCOVER_MINUTES
        else:
            ice_adder = ICE_BUILD_MINUTES
    else:
        ice_adder = 0

    seating_adder = SEATING_MODE_MINUTES[to_profile["seating_mode"]]
    panel_sets = ceil_div(to_profile["floor_protection_panels_required"], PANELS_PER_SET)
    panel_adder = panel_sets * PANEL_SET_MINUTES
    raw_minutes = int(to_profile["base_changeover_minutes"]) + ice_adder + seating_adder + panel_adder

    crew_factor = Fraction(int(crew_headcount), int(to_profile["crew_size_required"]))
    crew_factor = min(CREW_FACTOR_MAX, max(CREW_FACTOR_MIN, crew_factor))

    planned = math.ceil(Fraction(raw_minutes, 1) / crew_factor)
    if overnight:
        planned = math.ceil(Fraction(planned, 1) * OVERNIGHT_SLOWDOWN)
    return int(planned)


def whole_minutes_between(start, end):
    """Whole minutes from start to end, floored."""
    return int(math.floor((end - start).total_seconds() / 60.0))


def actual_turnaround_minutes(started_at, completed_at):
    return whole_minutes_between(started_at, completed_at)


# --- labor_call_cost_cents -------------------------------------------------
def labor_call_cost_cents(call, variant):
    rate = Decimal(LABOR_BASE_RATE_CENTS_PER_HOUR[call["craft"]])
    guaranteed = dec(call["guaranteed_hours"])
    if variant == "ESTIMATED":
        seconds = Decimal(int((call["call_end_utc"] - call["call_start_utc"]).total_seconds()))
        scheduled_hours = seconds / Decimal(3600)
        billable = max(guaranteed, scheduled_hours)
    else:
        billable = max(guaranteed, dec(call["actual_hours"]))
    straight = min(billable, OT_THRESHOLD_HOURS)
    overtime = max(Decimal(0), billable - OT_THRESHOLD_HOURS)
    multiplier = OVERNIGHT_RATE_MULTIPLIER if call["overnight"] else Decimal(1)
    per_head = round_half_up(rate * (straight + overtime * OT_MULTIPLIER) * multiplier, 0)
    return int(per_head) * int(call["headcount"])


# --- labor_cancellation_fee_cents -----------------------------------------
def labor_cancellation_fee_cents(call, now):
    seconds = Decimal(int((call["call_start_utc"] - now).total_seconds()))
    notice_hours = seconds / Decimal(3600)
    if notice_hours >= CANCEL_FREE_NOTICE_HOURS:
        factor = Decimal("0.00")
    elif notice_hours >= CANCEL_PARTIAL_NOTICE_HOURS:
        factor = CANCEL_PARTIAL_FACTOR
    else:
        factor = CANCEL_LATE_FACTOR
    return int(round_half_up(Decimal(int(call["estimated_cost_cents"])) * factor, 0))


# --- displacement_settlement_cents ----------------------------------------
def displacement_settlement_cents(booking, now):
    base = DISPLACEMENT_BASE_CENTS[booking["hold_tier"]]
    notice_days = (booking["event_start_utc"] - now).days
    if notice_days >= NOTICE_LONG_DAYS:
        notice_multiplier = Decimal("0.25")
    elif notice_days >= NOTICE_MID_DAYS:
        notice_multiplier = Decimal("0.60")
    else:
        notice_multiplier = Decimal("1.00")
    subtotal = int(round_half_up(Decimal(base) * notice_multiplier, 0))
    if subtotal >= ADMIN_HIGH_SUBTOTAL_CENTS:
        admin_rate = Decimal("0.08")
    elif subtotal >= ADMIN_MID_SUBTOTAL_CENTS:
        admin_rate = Decimal("0.05")
    else:
        admin_rate = Decimal("0.03")
    admin_fee = int(round_half_up(Decimal(subtotal) * admin_rate, 0))
    return subtotal + admin_fee


# --- condensation_risk_score ----------------------------------------------
def condensation_risk_score(sheet):
    required = dec(sheet["required_dehumidification_lph"])
    applied = dec(sheet["dehumidification_lph_applied"])
    if required == 0:
        dehum_deficit = Decimal(0)
    else:
        dehum_deficit = max(Decimal(0), (required - applied) / required)
    cover_load = min(Decimal(1), dec(sheet["cover_hours_accumulated"]) / COVER_HOURS_LIMIT)
    thickness_deficit = max(
        Decimal(0),
        (NOMINAL_THICKNESS_MM - dec(sheet["sheet_thickness_mm"])) / NOMINAL_THICKNESS_MM,
    )
    blended = W_DEHUM * dehum_deficit + W_COVER * cover_load + W_THICKNESS * thickness_deficit
    return round_half_up(Decimal(100) * blended, 2)


def cover_hours_delta(cover_installed_at, now):
    seconds = Decimal(int((now - cover_installed_at).total_seconds()))
    return round_half_up(seconds / Decimal(3600), 3)


# --- rigging_committed_load_kg --------------------------------------------
def _closed_overlap(a_start, a_end, b_start, b_end):
    return b_start <= a_end and a_start <= b_end


def rigging_peer_load(venue_id, candidate_start, candidate_end, exclude_id=None):
    total = Decimal(0)
    for booking in db.bookings.values():
        if booking["venue_id"] != venue_id or booking["status"] != "CONFIRMED":
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        if _closed_overlap(candidate_start, candidate_end,
                           booking["event_start_utc"], booking["event_end_utc"]):
            total += dec(booking["rigging_load_kg"])
    return round_half_up(total, 2)


def rigging_committed_load_kg(venue_id):
    """The stored arena figure: the logical clock instant as a zero-length window."""
    instant = now_logical()
    return rigging_peer_load(venue_id, instant, instant)


# --- equipment_units_available -------------------------------------------
def outstanding_issued_units(asset_id):
    total = 0
    for issue in db.issues.values():
        if issue["asset_id"] == asset_id and issue["status"] == "ISSUED":
            total += int(issue["units_issued"])
    return total


def equipment_units_available(asset):
    return int(asset["units_total"]) - int(asset["units_out_of_service"]) \
        - outstanding_issued_units(asset["id"])


def service_due(asset):
    return int(asset["cycles_since_service"]) >= int(asset["service_interval_cycles"])


# --- arena derived fields -------------------------------------------------
def live_ice_sheet(venue_id):
    for sheet in db.ice_sheets.values():
        if sheet["venue_id"] == venue_id and sheet["status"] != "REMOVED":
            return sheet
    return None


def ice_deck_status(venue_id):
    sheet = live_ice_sheet(venue_id)
    return sheet["status"] if sheet else "NONE"


def open_hold_count(venue_id):
    count = 0
    for booking in db.bookings.values():
        if booking["venue_id"] == venue_id and booking["status"] in ("HELD", "CHALLENGED"):
            count += 1
    return count


def holds_consumed(tenant_id):
    count = 0
    for booking in db.bookings.values():
        if booking.get("tenant_id") == tenant_id and booking["status"] in LIVE_BOOKING_STATES:
            count += 1
    return count


# --- floor protection ----------------------------------------------------
def required_panel_sets(to_profile):
    return ceil_div(to_profile["floor_protection_panels_required"], PANELS_PER_SET)


def issued_floor_panel_sets(order_id):
    total = 0
    for issue in db.issues.values():
        if issue["changeover_order_id"] != order_id or issue["status"] != "ISSUED":
            continue
        asset = db.assets.get(issue["asset_id"])
        if asset is not None and asset["asset_class"] == "FLOOR_PANEL_SET":
            total += int(issue["units_issued"])
    return total
