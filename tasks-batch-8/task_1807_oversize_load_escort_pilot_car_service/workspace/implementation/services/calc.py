"""Calculation rules (scaffold section 1.3) — pure functions, no mutation."""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- Constants ----------------------------------------------------------------
STATE_RULES = {
    "TX": {"rear_threshold": 168, "front_threshold": 180, "two_front_threshold": 192,
           "pole_threshold": 174, "police_width_threshold": 192, "police_weight_threshold": 200000},
    "OK": {"rear_threshold": 168, "front_threshold": 174, "two_front_threshold": 186,
           "pole_threshold": 168, "police_width_threshold": 180, "police_weight_threshold": 180000},
    "KS": {"rear_threshold": 156, "front_threshold": 180, "two_front_threshold": 192,
           "pole_threshold": 174, "police_width_threshold": 192, "police_weight_threshold": 250000},
    "LA": {"rear_threshold": 144, "front_threshold": 168, "two_front_threshold": 180,
           "pole_threshold": 162, "police_width_threshold": 180, "police_weight_threshold": 150000},
}
VALID_STATE_CODES = tuple(STATE_RULES.keys())
SURVEY_MARGIN_INCHES = 6

CLEARANCE_BUFFER_INCHES = 6

HOURLY_RATE_CENTS = 9000
AVG_SPEED_MPH = 50
POLE_SURCHARGE_CENTS = 15000
POLICE_COORDINATION_FEE_CENTS = 40000
SURVEY_FEE_CENTS = 25000
QUOTE_TTL_HOURS = 72

MIN_ASSIGNMENT_HOURS = 4
ROUNDING_INCREMENT_MINUTES = 30

STANDBY_GRACE_MINUTES = 30
STANDBY_INCREMENT_MINUTES = 15
STANDBY_RATE_CENTS = 7500
BILLABLE_DELAY_CAUSES = ("CARRIER_DELAY", "MECHANICAL_BREAKDOWN", "DOCUMENTATION_ISSUE")
NON_BILLABLE_DELAY_CAUSES = ("WEATHER", "CURFEW_HOLD", "POLICE_DIRECTED", "ROAD_CLOSURE")
DELAY_CAUSES = BILLABLE_DELAY_CAUSES + NON_BILLABLE_DELAY_CAUSES

VOLUME_TIER1_THRESHOLD_CENTS = 100000
VOLUME_TIER1_PCT = Decimal("0.02")
VOLUME_TIER2_THRESHOLD_CENTS = 500000
VOLUME_TIER2_PCT = Decimal("0.05")
FUEL_SURCHARGE_PCT = Decimal("0.07")

DEADHEAD_BUFFER_MINUTES = 60

CURFEW_WINDOWS_UTC = {
    "TX": [("07:00", "09:00"), ("16:00", "18:30")],
    "OK": [("07:00", "09:00"), ("16:30", "18:30")],
    "KS": [("06:30", "08:30"), ("16:00", "18:00")],
    "LA": [("06:30", "09:00"), ("15:30", "18:00")],
}

LIABILITY_CAP_CENTS = 25000000
ESCORT_DEDUCTIBLE_CENTS = 50000

RELIABILITY_INITIAL = 100
HIGH_FAULT_THRESHOLD_PCT = 50
HIGH_FAULT_PENALTY = 35
PARTIAL_FAULT_PENALTY = 10
RELIABILITY_SUSPENSION_FLOOR = 40

CANCEL_FEE_TIERS = {
    "DRAFT": ("NONE", Decimal("0")),
    "QUOTED": ("NONE", Decimal("0")),
    "BOOKED": ("TIER_10", Decimal("0.10")),
    "CLEARED": ("TIER_10", Decimal("0.10")),
    "SCHEDULED": ("TIER_25", Decimal("0.25")),
    "EN_ROUTE": ("TIER_50", Decimal("0.50")),
    "ON_HOLD": ("TIER_50", Decimal("0.50")),
}

INCIDENT_TYPES = ("CARGO_DAMAGE", "PROPERTY_DAMAGE", "TRAFFIC_VIOLATION", "INJURY", "EQUIPMENT_DAMAGE")
OBSTRUCTION_TYPES = ("BRIDGE", "WIRE", "SIGN", "OTHER")
OBSTRUCTION_DISPOSITIONS = ("PASSABLE", "PASSABLE_WITH_POLE", "REQUIRES_REROUTE")
POSITIONS = ("FRONT", "REAR")
SURVEY_OUTCOMES = ("ACCEPTED", "REJECTED")


def round_half_up(dec):
    """Round a Decimal to whole cents, half up."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- CALC-1: escort_requirement_determination ---------------------------------
def determine_requirements(job, leg):
    """Sets the five requirement fields on the leg dict in place."""
    rules = STATE_RULES[leg["state_code"]]
    w = job["width_inches"]
    h = job["height_inches"]
    gw = job["gross_weight_lbs"]
    leg["required_rear_escorts"] = 1 if w >= rules["rear_threshold"] else 0
    if w >= rules["two_front_threshold"]:
        leg["required_front_escorts"] = 2
    elif w >= rules["front_threshold"]:
        leg["required_front_escorts"] = 1
    else:
        leg["required_front_escorts"] = 0
    leg["requires_height_pole"] = h >= rules["pole_threshold"]
    leg["requires_police_escort"] = (
        w >= rules["police_width_threshold"] or gw >= rules["police_weight_threshold"]
    )
    leg["requires_route_survey"] = (
        leg["requires_height_pole"] or h >= rules["pole_threshold"] - SURVEY_MARGIN_INCHES
    )


def reset_requirements(leg):
    leg["required_front_escorts"] = 0
    leg["required_rear_escorts"] = 0
    leg["requires_height_pole"] = False
    leg["requires_police_escort"] = False
    leg["requires_route_survey"] = False


# --- CALC-2: clearance_assessment (surveyed variant) ---------------------------
def clearance_verdict_for(height_inches, min_overhead):
    required = height_inches + CLEARANCE_BUFFER_INCHES
    return "PASS" if min_overhead >= required else "FAIL"  # equality passes


# --- CALC-3: quote_estimate ----------------------------------------------------
def quote_estimate(job, legs):
    """Returns (quoted_cents, total_escort_positions)."""
    base_est = 0
    equipment_est = 0
    total_positions = 0
    for leg in legs:
        half_hours = math.ceil(job_leg_half_hours(leg))
        positions = leg["required_front_escorts"] + leg["required_rear_escorts"]
        total_positions += positions
        base_est += half_hours * (HOURLY_RATE_CENTS // 2) * positions
        if leg["requires_height_pole"]:
            equipment_est += POLE_SURCHARGE_CENTS
        if leg["requires_police_escort"]:
            equipment_est += POLICE_COORDINATION_FEE_CENTS
        if leg["requires_route_survey"]:
            equipment_est += SURVEY_FEE_CENTS
    return base_est + equipment_est, total_positions


def job_leg_half_hours(leg):
    """estimated_hours * 2, already ceiled: ceil(distance / AVG_SPEED * 2)."""
    return math.ceil(leg["distance_miles"] * 2 / AVG_SPEED_MPH)


# --- CALC-4: final_billing ------------------------------------------------------
def final_billing(activated_at, completed_at):
    """Returns (billable_hours, assignment_fee_cents)."""
    raw_minutes = int((completed_at - activated_at).total_seconds() // 60)
    half_units = math.ceil(raw_minutes / ROUNDING_INCREMENT_MINUTES)
    hours = half_units / 2
    billable_hours = max(MIN_ASSIGNMENT_HOURS, hours)
    fee = round_half_up(Decimal(str(billable_hours)) * HOURLY_RATE_CENTS)
    if billable_hours == int(billable_hours):
        billable_hours = int(billable_hours)
    return billable_hours, fee


# --- CALC-5: standby_billing ------------------------------------------------------
def standby_billing(cause, raw_minutes, total_escort_positions):
    """Returns (billable_minutes, standby_amount_cents)."""
    if cause in NON_BILLABLE_DELAY_CAUSES:
        billable_minutes = 0
    else:
        chargeable = max(0, raw_minutes - STANDBY_GRACE_MINUTES)
        billable_minutes = (
            math.ceil(chargeable / STANDBY_INCREMENT_MINUTES) * STANDBY_INCREMENT_MINUTES
        )
    # (billable/60) * 7500 * positions; billable is a multiple of 15 -> integral
    standby_amount = (billable_minutes * STANDBY_RATE_CENTS // 60) * total_escort_positions
    return billable_minutes, standby_amount


# --- CALC-6: invoice_total_composition -------------------------------------------
def compose_invoice(job, legs, completed_assignments, closed_delays, settled_incidents,
                    carrier_ytd, adjustment_delta):
    """Pinned evaluation order. Returns dict of all monetary fields."""
    base = sum(a["assignment_fee_cents"] or 0 for a in completed_assignments)
    equipment = 0
    for leg in legs:
        if leg["requires_height_pole"]:
            equipment += POLE_SURCHARGE_CENTS
        if leg["requires_police_escort"]:
            equipment += POLICE_COORDINATION_FEE_CENTS
        if leg["requires_route_survey"]:
            equipment += SURVEY_FEE_CENTS
    standby = sum(d["standby_amount_cents"] or 0 for d in closed_delays)
    subtotal = base + equipment + standby
    tier_basis = carrier_ytd + subtotal
    if tier_basis >= VOLUME_TIER2_THRESHOLD_CENTS:
        pct = VOLUME_TIER2_PCT
    elif tier_basis >= VOLUME_TIER1_THRESHOLD_CENTS:
        pct = VOLUME_TIER1_PCT
    else:
        pct = Decimal("0")
    volume_discount = round_half_up(Decimal(subtotal) * pct)
    fuel = round_half_up(Decimal(base + equipment) * FUEL_SURCHARGE_PCT)
    cancellation_fee = job["cancel_fee_cents"] or 0
    chargebacks = sum(i["escort_share_cents"] or 0 for i in settled_incidents)
    total = (subtotal - volume_discount + fuel + cancellation_fee
             - chargebacks + adjustment_delta)
    return {
        "base_charges_cents": base,
        "equipment_charges_cents": equipment,
        "standby_total_cents": standby,
        "subtotal_cents": subtotal,
        "volume_discount_cents": volume_discount,
        "fuel_surcharge_cents": fuel,
        "cancellation_fee_cents": cancellation_fee,
        "incident_chargebacks_cents": chargebacks,
        "total_cents": total,
    }


# --- CALC-8: escort_assignment_overlap_check --------------------------------------
def buffered_window(job):
    buf = timedelta(minutes=DEADHEAD_BUFFER_MINUTES)
    return job["window_start_at"] - buf, job["window_end_at"] + buf


def windows_conflict(job_a, job_b):
    """Strict intersection of buffered windows; touching endpoints do NOT conflict."""
    a_start, a_end = buffered_window(job_a)
    b_start, b_end = buffered_window(job_b)
    return a_start < b_end and b_start < a_end


# --- CALC-9: curfew_window_validation ---------------------------------------------
def _hm(hhmm):
    hh, mm = hhmm.split(":")
    return int(hh), int(mm)


def traversed_dates(entry, exit_):
    """UTC calendar dates touched by the half-open interval [entry, exit_)."""
    dates = []
    d = entry.date()
    last = exit_.date()
    while d <= last:
        day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        if entry < day_end and day_start < exit_:
            dates.append(d)
        d = d + timedelta(days=1)
    return dates


def curfew_violation(state_code, entry, exit_):
    """True when [entry, exit_) intersects any curfew window on any traversed date."""
    windows = CURFEW_WINDOWS_UTC[state_code]
    for d in traversed_dates(entry, exit_):
        day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        for c_start_s, c_end_s in windows:
            sh, sm = _hm(c_start_s)
            eh, em = _hm(c_end_s)
            c_start = day_start + timedelta(hours=sh, minutes=sm)
            c_end = day_start + timedelta(hours=eh, minutes=em)
            if entry < c_end and c_start < exit_:
                return True
    return False


def permit_covers(permit, entry, exit_):
    """Schedule coverage: ISSUED, window covers traversal, no holiday closure on traversed dates."""
    if permit["permit_status"] != "ISSUED":
        return False
    if not (permit["valid_from"] <= entry and permit["valid_until"] >= exit_):
        return False
    closures = set(permit["holiday_closure_dates"])
    if closures:
        for d in traversed_dates(entry, exit_):
            if d.isoformat() in closures:
                return False
    return True


# --- CALC-10: incident_liability_assessment ----------------------------------------
def assess_liability(claimed_amount_cents, fault_share_pct):
    assessed = min(claimed_amount_cents, LIABILITY_CAP_CENTS)
    raw_share = round_half_up(Decimal(assessed) * Decimal(fault_share_pct) / Decimal(100))
    escort_share = max(0, raw_share - ESCORT_DEDUCTIBLE_CENTS)
    return assessed, escort_share


# --- CALC-12: cancellation_fee ------------------------------------------------------
def cancellation_fee(pre_cancel_status, quoted_cents):
    tier, pct = CANCEL_FEE_TIERS[pre_cancel_status]
    if quoted_cents is None:
        return tier, 0
    return tier, round_half_up(Decimal(quoted_cents) * pct)


# --- CALC-13: escort_reliability_update ---------------------------------------------
def reliability_delta(fault_share_pct):
    if fault_share_pct >= HIGH_FAULT_THRESHOLD_PCT:
        return -HIGH_FAULT_PENALTY
    if fault_share_pct >= 1:
        return -PARTIAL_FAULT_PENALTY
    return 0


def apply_reliability(current_score, fault_share_pct):
    return max(0, min(100, current_score + reliability_delta(fault_share_pct)))
