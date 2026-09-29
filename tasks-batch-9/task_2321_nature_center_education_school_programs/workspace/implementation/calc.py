"""All ten calculation rules (PRD 3.2, 3.3, 3.4, 3.5, 3.8, 3.9).

Money is always an integer count of cents; rounding is half-up and happens only
at the points each formula pins.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
MIN_BILLABLE_STUDENTS = 10
TRAVEL_BASE_CENTS = 4000
TRAVEL_PER_MILE_CENTS = 175
BOX_TRUCK_TRAVEL_MULTIPLIER = Decimal("2.0")
RAIN_DIVERT_CREDIT_PCT = Decimal("0.20")

EQUITY_TIER_1_MIN_TITLE_I_PCT = Decimal("0.75")
EQUITY_TIER_2_MIN_TITLE_I_PCT = Decimal("0.50")
EQUITY_TIER_3_MIN_TITLE_I_PCT = Decimal("0.25")
TIER_CAP_PCT = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("0.70"),
    "TIER_3": Decimal("0.40"),
    "NONE": Decimal("0.00"),
}
MIN_SCHOOL_CONTRIBUTION_CENTS_PER_STUDENT = 150
TRANSPORT_PER_MILE_CENTS = 260

WELFARE_RESTRICTED_PCT = Decimal("0.60")

HIGH_SENSITIVITY_MAX_PERSONS = 25

EDUCATOR_TRAVEL_BUFFER_ONSITE_MINUTES = 45
EDUCATOR_TRAVEL_BUFFER_OUTREACH_MINUTES = 60
EDUCATOR_WEEKLY_CAP_MINUTES = {"SEASONAL_EDUCATOR": 360, "STAFF_NATURALIST": 600}
TRAINING_VALIDITY_DAYS = 365

MAX_ASSESSMENT_SCORE = Decimal("20")
TEACHER_WEIGHT_STANDARDS = Decimal("0.50")
TEACHER_WEIGHT_ENGAGEMENT = Decimal("0.30")
TEACHER_WEIGHT_LOGISTICS = Decimal("0.20")
GAIN_WEIGHT = Decimal("0.60")
TEACHER_WEIGHT = Decimal("0.40")
FIDELITY_FULL = Decimal("1.00")
FIDELITY_DIVERTED = Decimal("0.80")
FIDELITY_NONE = Decimal("0.00")
THIN_ALIGNMENT_PENALTY = Decimal("0.90")
THIN_ALIGNMENT_THRESHOLD = 3

SCHOOL_PROBATION_STRIKES = 1
SCHOOL_SUSPENSION_STRIKES = 2
NO_SHOW_FEE_CENTS = 7500

VEHICLE_CLASS_WEIGHT_THRESHOLD_KG = Decimal("250")

HANDLING_TIER_RANK = {"NONE": 0, "TIER_1": 1, "TIER_2": 2}
GRADE_BANDS = ("K_2", "G3_5", "G6_8", "G9_12")


def D(value):
    return Decimal(str(value))


def round_half_up_cents(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    if value < low:
        return D(low)
    if value > high:
        return D(high)
    return value


# ------------------------------------------------- chaperone_requirement
def required_chaperones(student_count, ratio):
    if not ratio:
        return 0
    return int(math.ceil(float(student_count) / float(ratio)))


# ------------------------------------------------- booking_fee_assessment
def volume_discount_pct(billable_students):
    if billable_students >= 60:
        return Decimal("0.15")
    if billable_students >= 30:
        return Decimal("0.10")
    if billable_students >= 15:
        return Decimal("0.05")
    return Decimal("0.00")


def booking_fee(headcount, offering, school, box_truck, rain_diverted):
    """Six pinned steps (PRD 3.8)."""
    billable_students = max(MIN_BILLABLE_STUDENTS, int(headcount or 0))
    discount_pct = volume_discount_pct(billable_students)
    per_student_cents = round_half_up_cents(
        D(offering["base_fee_cents_per_student"]) * (Decimal("1") - discount_pct)
    )
    program_fee_cents = per_student_cents * billable_students

    if offering["delivery_mode"] == "OUTREACH_AT_SCHOOL":
        multiplier = BOX_TRUCK_TRAVEL_MULTIPLIER if box_truck else Decimal("1.0")
        travel_fee_cents = round_half_up_cents(
            D(TRAVEL_BASE_CENTS)
            + D(TRAVEL_PER_MILE_CENTS) * D(school["distance_miles"]) * multiplier
        )
    else:
        travel_fee_cents = 0

    gross_cents = program_fee_cents + travel_fee_cents
    if rain_diverted:
        gross_cents = round_half_up_cents(D(gross_cents) * (Decimal("1") - RAIN_DIVERT_CREDIT_PCT))
    return gross_cents


# ------------------------------------------------- equity tier / standing
def equity_tier(title_i_pct):
    pct = D(title_i_pct)
    if pct >= EQUITY_TIER_1_MIN_TITLE_I_PCT:
        return "TIER_1"
    if pct >= EQUITY_TIER_2_MIN_TITLE_I_PCT:
        return "TIER_2"
    if pct >= EQUITY_TIER_3_MIN_TITLE_I_PCT:
        return "TIER_3"
    return "NONE"


def school_standing(no_show_strikes):
    if no_show_strikes >= SCHOOL_SUSPENSION_STRIKES:
        return "SUSPENDED"
    if no_show_strikes >= SCHOOL_PROBATION_STRIKES:
        return "PROBATION"
    return "ACTIVE"


# ------------------------------------------------- aid_award_allocation
def aid_award(application, booking, school, fund, fund_available_cents, fund_transport_awarded_cents):
    """Nine pinned steps (PRD 3.8).  Returns (scholarship, transport)."""
    if booking["delivery_status"] == "DELIVERED":
        gross_cents = booking["final_gross_fee_cents"]
    else:
        gross_cents = booking["provisional_gross_fee_cents"]

    tier_cap_pct = TIER_CAP_PCT.get(school.get("equity_tier") or "NONE", Decimal("0.00"))
    contribution_floor_cents = MIN_SCHOOL_CONTRIBUTION_CENTS_PER_STUDENT * booking["student_count"]

    max_scholarship_cents = min(
        application["requested_scholarship_cents"],
        round_half_up_cents(D(gross_cents) * tier_cap_pct),
        max(0, gross_cents - contribution_floor_cents),
    )

    transport_entitlement_cents = round_half_up_cents(
        D(TRANSPORT_PER_MILE_CENTS) * D(school["distance_miles"]) * Decimal("2")
    )
    remaining_sublimit_cents = max(
        0,
        transport_sublimit_cents(fund) - fund_transport_awarded_cents,
    )
    max_transport_cents = min(
        application["requested_transport_cents"],
        transport_entitlement_cents,
        remaining_sublimit_cents,
    )

    budget_cents = (
        fund_available_cents
        + application["requested_scholarship_cents"]
        + application["requested_transport_cents"]
    )

    awarded_scholarship_cents = min(max_scholarship_cents, budget_cents)
    if awarded_scholarship_cents < 0:
        awarded_scholarship_cents = 0
    budget_cents = budget_cents - awarded_scholarship_cents

    awarded_transport_cents = min(max_transport_cents, budget_cents)
    if awarded_transport_cents < 0:
        awarded_transport_cents = 0

    return awarded_scholarship_cents, awarded_transport_cents


def transport_sublimit_cents(fund):
    return round_half_up_cents(D(fund["total_cents"]) * D(fund["transport_sublimit_pct"]))


# ------------------------------------------------- welfare posture
def welfare_posture(permit_status, care_status, projected_minutes, cap_minutes):
    if permit_status != "ACTIVE" or care_status in ("VET_HOLD", "RETIRED"):
        return "BLOCKED"
    if projected_minutes >= cap_minutes:
        return "BLOCKED"
    if projected_minutes >= round_half_up_cents(D(cap_minutes) * WELFARE_RESTRICTED_PCT):
        return "RESTRICTED"
    return "OPEN"


def effective_contact_rule(posture, contact_rule):
    if posture == "BLOCKED":
        return "NO_PUBLIC_CONTACT"
    if posture == "RESTRICTED" and contact_rule == "SUPERVISED_TOUCH":
        return "VIEW_ONLY"
    return contact_rule


# ------------------------------------------------- learning gain index
def learning_gain_index(report, booking, offering):
    pre = D(report["student_pre_score_avg"])
    post = D(report["student_post_score_avg"])
    headroom = MAX_ASSESSMENT_SCORE - pre
    if headroom <= 0:
        normalized_gain = Decimal("0")
    else:
        normalized_gain = (post - pre) / headroom
    normalized_gain = clamp(normalized_gain, 0, 1)

    teacher_composite = (
        TEACHER_WEIGHT_STANDARDS * D(report["teacher_score_standards_alignment"])
        + TEACHER_WEIGHT_ENGAGEMENT * D(report["teacher_score_engagement"])
        + TEACHER_WEIGHT_LOGISTICS * D(report["teacher_score_logistics"])
    ) / Decimal("5")

    if booking["delivery_status"] == "DELIVERED" and booking.get("rain_diverted_to_offering_id") is None:
        fidelity = FIDELITY_FULL
    elif booking["delivery_status"] == "DELIVERED":
        fidelity = FIDELITY_DIVERTED
    else:
        fidelity = FIDELITY_NONE

    if offering["standard_alignment_count"] < THIN_ALIGNMENT_THRESHOLD:
        alignment_factor = THIN_ALIGNMENT_PENALTY
    else:
        alignment_factor = Decimal("1.00")

    combined = (GAIN_WEIGHT * normalized_gain + TEACHER_WEIGHT * teacher_composite) * fidelity * alignment_factor
    return float(round_half_up(clamp(combined, 0, 1), 2))


# ------------------------------------------------- manifest vehicle class
def vehicle_class(total_weight_kg):
    return "BOX_TRUCK" if D(total_weight_kg) > VEHICLE_CLASS_WEIGHT_THRESHOLD_KG else "VAN"


# ------------------------------------------------- educator buffers
def educator_buffer_minutes(delivery_mode):
    if delivery_mode == "OUTREACH_AT_SCHOOL":
        return EDUCATOR_TRAVEL_BUFFER_OUTREACH_MINUTES
    return EDUCATOR_TRAVEL_BUFFER_ONSITE_MINUTES
