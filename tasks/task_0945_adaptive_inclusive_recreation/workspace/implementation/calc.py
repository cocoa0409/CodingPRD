"""The nineteen declared calculations (PRD 2.8, 3.2-3.9)."""

from decimal import ROUND_HALF_UP, Decimal

import lookups as L
from store import (
    add_days,
    date_of_instant,
    db,
    parse_date,
    parse_instant,
    whole_years_between,
)

# --- global constants (PRD 2.8, 3.5, 3.7, 3.8) -----------------------------
SUPPORT_POINTS = {
    "INDEPENDENT": 25,
    "INTERMITTENT": 50,
    "SUBSTANTIAL": 100,
    "ONE_TO_ONE": 0,
}
STAFF_POINT_CAPACITY = 400
MIN_GROUP_STAFF = 1
RISK_MULTIPLIER_BP = {"LOW": 10000, "MODERATE": 12500, "HIGH": 15000}
ASSESSMENT_VALIDITY_DAYS = 365
SESSION_ENROLLMENT_CUTOFF_HOURS = 24
STAFF_TURNAROUND_BUFFER_MINUTES = 30
TRANSPORT_ARRIVAL_BUFFER_MINUTES = 15
MAX_SESSION_UNLOCKS = 2
SIBLING_DISCOUNT_BP = 1500
SIBLING_DISCOUNT_MIN_ENROLLED = 2
TRANSPORT_BASE_FARE_CENTS = 300
TRANSPORT_PER_MILE_CENTS = 85
TRANSPORT_ACCESSIBLE_SURCHARGE_CENTS = 250
FUNDING_EXHAUSTED_AT_AVAILABLE_CENTS = 0
SUBSIDY_REQUIRED_INCOME_BANDS = ("BAND_A", "BAND_B")
INSPECTION_INTERVAL_DAYS = 180
WEIGHT_CAPACITY_TOLERANCE_KG = 0
WAITLIST_EQUITY_SCHOLARSHIP_BONUS = 50

LIVE_ENROLLMENT_STATUSES = ("REQUESTED", "WAITLISTED", "CONFIRMED")
LIVE_RESERVATION_STATUSES = ("HELD", "CHECKED_OUT")
LIVE_BOOKING_STATUSES = ("RESERVED", "CONFIRMED", "RIDDEN")
LIVE_ASSIGNMENT_STATUSES = ("PROPOSED", "CONFIRMED")


# --- rounding discipline (PRD 2.8) -----------------------------------------

def round_half_up(numerator, denominator):
    """Half up, away from zero, on an exact rational."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount, basis_points):
    """Multiply by a basis-point figure, divide by 10000, round half up."""
    return round_half_up(amount * basis_points, 10000)


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def support_points(tier):
    return SUPPORT_POINTS.get(tier, 0)


# --- participant derivations -----------------------------------------------

def age_years(participant):
    birth = parse_date(participant.get("date_of_birth"))
    if birth is None:
        return None
    return whole_years_between(birth, db.clock_date)


def effective_support_tier_now(participant):
    active = L.active_assessment(participant)
    return active["support_tier"] if active else None


def effective_support_tier(participant, session):
    """CURRENT while the session is not delivered; AS_OF_SESSION once it is."""
    if session is not None and session["status"] == "DELIVERED":
        start = parse_instant(session["start_at"])
        candidates = []
        for row in L.assessments_of_participant(participant):
            if row["status"] not in ("ACTIVE", "SUPERSEDED"):
                continue
            effective_from = parse_instant(row["effective_from"])
            if effective_from is not None and start is not None and effective_from <= start:
                candidates.append(row)
        if not candidates:
            return None
        candidates.sort(
            key=lambda r: (parse_instant(r["effective_from"]), r["created_at"], r["_seq"]),
            reverse=True,
        )
        return candidates[0]["support_tier"]
    return effective_support_tier_now(participant)


# --- fee scale + pricing ---------------------------------------------------

def fee_scale_band_match(participant):
    candidates = [
        band
        for band in db.rows("fee_scale_bands")
        if band["household_size_min"] <= participant["household_size"] <= band["household_size_max"]
        and band["income_band"] == participant["income_band"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (-b["household_size_min"], b["created_at"], b["_seq"]))
    return candidates[0]


def participant_session_fee_cents(band, program, session):
    if program["pricing_mode"] == "PER_SESSION":
        return apply_bp(band["per_session_cents"], program["fee_multiplier_bp"])
    series_total = apply_bp(band["series_cents"], program["fee_multiplier_bp"])
    count = program["scheduled_session_count"]
    base = series_total // count
    remainder = series_total - base * count
    return base + (remainder if session["sequence_number"] == 1 else 0)


# --- staffing --------------------------------------------------------------

def required_group_staff_count(session, roster_status):
    program = L.program_of_session(session)
    pooled = []
    for enrollment in L.enrollments_of_session(session):
        if enrollment["enrollment_status"] != roster_status:
            continue
        if enrollment.get("effective_support_tier_at_session") != "ONE_TO_ONE":
            pooled.append(enrollment)
    if not pooled:
        return 0
    points = sum(support_points(e.get("effective_support_tier_at_session")) for e in pooled)
    multiplier = RISK_MULTIPLIER_BP[program["risk_tier"]]
    weighted = ceil_div(points * multiplier, 10000)
    return max(MIN_GROUP_STAFF, ceil_div(weighted, STAFF_POINT_CAPACITY))


def pooled_support_points(session, roster_status="CONFIRMED"):
    total = 0
    for enrollment in L.enrollments_of_session(session):
        if enrollment["enrollment_status"] != roster_status:
            continue
        if enrollment.get("effective_support_tier_at_session") == "ONE_TO_ONE":
            continue
        total += support_points(enrollment.get("effective_support_tier_at_session"))
    return total


def staff_certification_verdict(staff_id, program, check_date):
    """(has_every_required_row, every_required_row_unexpired)."""
    required = program.get("required_certification_types") or []
    certifications = L.certifications_of_staff(staff_id)
    has_all = True
    unexpired = True
    for wanted in required:
        rows = [c for c in certifications if c["certification_type"] == wanted]
        if not rows:
            has_all = False
            continue
        if not any(parse_date(c["expires_on"]) >= check_date for c in rows):
            unexpired = False
    return has_all, unexpired


def staff_qualified(staff_id, program, check_date):
    has_all, unexpired = staff_certification_verdict(staff_id, program, check_date)
    return has_all and unexpired


# --- equipment -------------------------------------------------------------

def equipment_fit_ok(item, program, participant):
    return (
        item["model_code"] == program.get("required_equipment_model_code")
        and item["size_code"] == program.get("required_equipment_size_code")
        and item["weight_capacity_kg"]
        >= participant["weight_kg"] + WEIGHT_CAPACITY_TOLERANCE_KG
    )


def equipment_condition_ok(item, session):
    if item["condition_status"] != "SERVICEABLE":
        return False
    if item["item_kind"] == "POOLED":
        return True
    due = parse_date(item.get("inspection_due_date"))
    session_date = date_of_instant(session["start_at"])
    return due is not None and due >= session_date


def equipment_available_ok(item):
    return item["pooled_available"] >= 1


# --- transport -------------------------------------------------------------

def transport_fare_cents(run, position_type):
    surcharge = (
        TRANSPORT_ACCESSIBLE_SURCHARGE_CENTS if position_type == "ACCESSIBLE" else 0
    )
    if run["fare_mode"] == "FLAT":
        return run["flat_fare_cents"] + surcharge
    tenths = TRANSPORT_BASE_FARE_CENTS * 10 + TRANSPORT_PER_MILE_CENTS * run["route_miles_x10"]
    return round_half_up(tenths, 10) + surcharge


# --- money -----------------------------------------------------------------

def sibling_discount_bp(enrollment):
    session = L.session_of_enrollment(enrollment)
    participant = L.participant_of_enrollment(enrollment)
    if session is None or participant is None:
        return 0
    household = participant["household_id"]
    seen = set()
    for other in L.enrollments_of_session(session):
        if other["enrollment_status"] != "CONFIRMED":
            continue
        other_participant = L.participant_of_enrollment(other)
        if other_participant is None:
            continue
        if other_participant["household_id"] == household:
            seen.add(other_participant["id"])
    return SIBLING_DISCOUNT_BP if len(seen) >= SIBLING_DISCOUNT_MIN_ENROLLED else 0


def family_responsibility_total_cents(copay_cents, transport_fee_cents, discount_bp, program):
    factor = 10000 - discount_bp
    if program["rounding_policy"] == "ROUND_PER_LINE":
        return round_half_up(copay_cents * factor, 10000) + round_half_up(
            transport_fee_cents * factor, 10000
        )
    return round_half_up((copay_cents + transport_fee_cents) * factor, 10000)


def settlement_status(enrollment, balance_cents):
    if enrollment["enrollment_status"] in ("WITHDRAWN", "DENIED"):
        return "VOIDED"
    if enrollment["enrollment_status"] in ("REQUESTED", "WAITLISTED"):
        return "QUOTED"
    if balance_cents == 0:
        return "SETTLED"
    return "OUTSTANDING"


# --- funding ---------------------------------------------------------------

def funding_source_selector():
    candidates = []
    for source in db.rows("funding_sources"):
        if source["status"] != "OPEN":
            continue
        if source["available_cents"] <= FUNDING_EXHAUSTED_AT_AVAILABLE_CENTS:
            continue
        period = L.period_of_source(source)
        if period is None or period["status"] != "OPEN":
            continue
        candidates.append(source)
    if not candidates:
        return None
    candidates.sort(
        key=lambda s: (s["priority_rank"], -s["available_cents"], s["created_at"], s["_seq"])
    )
    return candidates[0]


def scholarship_award_amount_cents(net_need_cents, source, requested_amount_cents):
    if requested_amount_cents is not None:
        return requested_amount_cents
    if source["award_mode"] == "NEED_PCT":
        raw = apply_bp(net_need_cents, source["award_pct_bp"])
        return min(raw, source["available_cents"])
    return min(net_need_cents, source["flat_award_cents"], source["available_cents"])


def encumbrance_release_cents(award):
    if award["status"] == "ENCUMBERED":
        return award["encumbered_cents"]
    if award["status"] == "PARTIALLY_DISBURSED":
        return award["encumbered_cents"] - award["disbursed_cents"]
    return 0


# --- waitlist --------------------------------------------------------------

def waitlist_priority_score(enrollment):
    program = L.program_of_enrollment(enrollment)
    if program is None or program["waitlist_policy"] == "FIFO":
        return 0
    score = support_points(enrollment.get("effective_support_tier_at_session"))
    for award in L.awards_of_enrollment(enrollment):
        if award["status"] in ("PROPOSED", "ENCUMBERED"):
            score += WAITLIST_EQUITY_SCHOLARSHIP_BONUS
            break
    return score


def promotion_candidates(session):
    rows = [e for e in L.enrollments_of_session(session) if e["enrollment_status"] == "WAITLISTED"]
    rows.sort(key=lambda e: (-waitlist_priority_score(e), e["created_at"], e["_seq"]))
    return rows


# --- goals -----------------------------------------------------------------

def ordered_ratings(goal):
    rows = L.ratings_of_goal(goal)
    rows.sort(
        key=lambda r: (parse_instant(r["rated_session_start_at"]), r["created_at"], r["_seq"]),
        reverse=True,
    )
    return rows


def goal_mastery_status(goal):
    ordered = ordered_ratings(goal)
    criterion = goal["mastery_criterion_score"]
    if goal["mastery_mode"] == "N_OF_M":
        window = ordered[: goal["mastery_window_m"]]
        if len(window) < goal["mastery_window_m"]:
            return False
        hits = sum(1 for r in window if r["score"] >= criterion)
        return hits >= goal["mastery_hits_n"]
    head = ordered[: goal["mastery_hits_n"]]
    if len(head) != goal["mastery_hits_n"]:
        return False
    return all(r["score"] >= criterion for r in head)


# --- consent ---------------------------------------------------------------

def accepted_signer_role(participant, consent):
    if consent["consent_type"] == "MEDICATION_ADMIN":
        return "LEGAL_GUARDIAN"
    if participant["guardianship_status"] == "SELF" and (age_years(participant) or 0) >= 18:
        return "SELF"
    return "LEGAL_GUARDIAN"


# --- eligibility -----------------------------------------------------------

def financial_gate_blocked(participant):
    for charge in db.rows("enrollment_charges"):
        if charge["status"] != "OUTSTANDING":
            continue
        enrollment = L.enrollment_of_charge(charge)
        if enrollment is None or enrollment["participant_id"] != participant["id"]:
            continue
        session = L.session_of_enrollment(enrollment)
        if session is not None and session["status"] == "DELIVERED":
            return True
    return False


def consent_gate_blocked(participant, program, check_date):
    if program is None:
        return False
    for wanted in program.get("required_consent_types") or []:
        satisfied = False
        for consent in L.consents_of_participant(participant):
            if consent["consent_type"] != wanted or consent["status"] != "SIGNED":
                continue
            expires = parse_date(consent["expires_on"])
            if expires is not None and expires >= check_date:
                satisfied = True
                break
        if not satisfied:
            return True
    return False


def assessment_gate_blocked(participant, check_date):
    active = L.active_assessment(participant)
    if active is None:
        return True
    assessed_on = parse_date(active["assessed_on"])
    if assessed_on is None:
        return True
    return add_days(assessed_on, ASSESSMENT_VALIDITY_DAYS) < check_date


def participant_enrollment_posture(participant, session):
    program = L.program_of_session(session) if session is not None else None
    check_date = date_of_instant(session["start_at"]) if session is not None else db.clock_date
    consent_blocked = consent_gate_blocked(participant, program, check_date)
    assessment_blocked = assessment_gate_blocked(participant, check_date)
    financial_blocked = financial_gate_blocked(participant)
    if participant["status"] != "ACTIVE":
        posture = "NOT_ACTIVE"
    elif consent_blocked:
        posture = "CONSENT_BLOCKED"
    elif assessment_blocked:
        posture = "ASSESSMENT_STALE"
    elif financial_blocked:
        posture = "FINANCIALLY_BLOCKED"
    else:
        posture = "CLEARED"
    return {
        "enrollment_posture": posture,
        "consent_gate_ok": not consent_blocked,
        "assessment_gate_ok": not assessment_blocked,
        "financial_gate_ok": not financial_blocked,
    }
