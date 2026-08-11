"""Derived-figure recomputation, the six cascades and the sub-gate walk."""

import calc
import lookups as L
from errors import ApiError
from store import (
    add_days,
    date_of_instant,
    db,
    parse_date,
    parse_instant,
    render_date,
    touch,
)

LIVE_ASSIGNMENT = ("PROPOSED", "CONFIRMED")
LIVE_BOOKING = ("RESERVED", "CONFIRMED", "RIDDEN")
LIVE_RESERVATION = ("HELD", "CHECKED_OUT")
LIVE_ENROLLMENT = ("REQUESTED", "WAITLISTED", "CONFIRMED")


# ---------------------------------------------------------------------------
# counter recomputation -- written so that the five conservation invariants of
# PRD 2.11 hold by construction rather than by bookkeeping luck.
# ---------------------------------------------------------------------------

def refresh_session_counters(session, bump=True):
    enrollments = L.enrollments_of_session(session)
    confirmed = [e for e in enrollments if e["enrollment_status"] == "CONFIRMED"]
    session["slots_committed"] = len(confirmed)
    session["slots_available"] = session["slot_capacity"] - len(confirmed)

    one_to_one = [
        e for e in confirmed if e.get("effective_support_tier_at_session") == "ONE_TO_ONE"
    ]
    session["one_to_one_committed"] = len(one_to_one)
    session["one_to_one_available"] = session["one_to_one_pool_size"] - len(one_to_one)

    assignments = L.assignments_of_session(session)
    session["assigned_group_staff_count"] = len(
        [
            a
            for a in assignments
            if a["assignment_role"] in ("LEAD", "GROUP") and a["status"] in LIVE_ASSIGNMENT
        ]
    )
    session["one_to_one_staffed"] = len(
        [
            a
            for a in assignments
            if a["assignment_role"] == "ONE_TO_ONE" and a["status"] in LIVE_ASSIGNMENT
        ]
    )

    if session["status"] in ("DRAFT", "OPEN", "STAFFING_LOCKED"):
        session["required_group_staff_planned"] = calc.required_group_staff_count(
            session, "CONFIRMED"
        )
    group_gap = max(0, session["required_group_staff_planned"] - session["assigned_group_staff_count"])
    one_to_one_gap = max(0, session["one_to_one_committed"] - session["one_to_one_staffed"])
    session["staffing_gap"] = group_gap + one_to_one_gap
    if bump:
        touch(session)
    return session


def refresh_run_counters(run, bump=True):
    bookings = L.bookings_of_run(run)
    accessible = len(
        [b for b in bookings if b["position_type"] == "ACCESSIBLE" and b["status"] in LIVE_BOOKING]
    )
    ambulatory = len(
        [b for b in bookings if b["position_type"] == "AMBULATORY" and b["status"] in LIVE_BOOKING]
    )
    run["accessible_committed"] = accessible
    run["accessible_available"] = run["accessible_positions"] - accessible
    run["ambulatory_committed"] = ambulatory
    run["ambulatory_available"] = run["ambulatory_seats"] - ambulatory
    if bump:
        touch(run)
    return run


def refresh_run_status(run):
    if (
        run["status"] == "PLANNED"
        and run["accessible_available"] == 0
        and run["ambulatory_available"] == 0
    ):
        run["status"] = "BOARDING_FULL"
        touch(run)
    elif run["status"] == "BOARDING_FULL" and (
        run["accessible_available"] > 0 or run["ambulatory_available"] > 0
    ):
        run["status"] = "PLANNED"
        touch(run)
    return run


def refresh_item_counters(item, bump=True):
    reservations = L.reservations_of_item(item)
    held = len([r for r in reservations if r["status"] == "HELD"])
    checked_out = len([r for r in reservations if r["status"] == "CHECKED_OUT"])
    item["pooled_held"] = held
    item["pooled_checked_out"] = checked_out
    item["pooled_available"] = item["pooled_total"] - held - checked_out
    if bump:
        touch(item)
    return item


# ---------------------------------------------------------------------------
# the enrolment charge
# ---------------------------------------------------------------------------

def recompute_charge(charge, bump=True):
    enrollment = L.enrollment_of_charge(charge)
    program = L.program_of_enrollment(enrollment)
    scholarship = 0
    for award in L.awards_of_enrollment(enrollment):
        if award["status"] in ("ENCUMBERED", "PARTIALLY_DISBURSED", "DISBURSED"):
            scholarship += award["encumbered_cents"]
    charge["scholarship_applied_cents"] = scholarship
    charge["copay_cents"] = max(0, charge["program_fee_cents"] - scholarship)
    charge["transport_fee_cents"] = sum(
        b["fare_cents"] for b in L.bookings_of_enrollment(enrollment) if b["status"] in LIVE_BOOKING
    )
    charge["sibling_discount_bp"] = calc.sibling_discount_bp(enrollment)
    charge["family_responsibility_cents"] = calc.family_responsibility_total_cents(
        charge["copay_cents"],
        charge["transport_fee_cents"],
        charge["sibling_discount_bp"],
        program,
    )
    charge["balance_cents"] = max(
        0, charge["family_responsibility_cents"] - charge["amount_paid_cents"]
    )
    charge["status"] = calc.settlement_status(enrollment, charge["balance_cents"])
    if bump:
        touch(charge)
    return charge


def household_sweep(enrollment):
    """PRD 3.8: recompute every OTHER charge whose enrolment is CONFIRMED on the
    same session and whose participant shares this household_id, created_at ASC.
    Exactly one sweep, no further passes."""
    session = L.session_of_enrollment(enrollment)
    participant = L.participant_of_enrollment(enrollment)
    if session is None or participant is None:
        return
    charges = []
    for other in L.enrollments_of_session(session):
        if other["id"] == enrollment["id"] or other["enrollment_status"] != "CONFIRMED":
            continue
        other_participant = L.participant_of_enrollment(other)
        if other_participant is None or other_participant["household_id"] != participant["household_id"]:
            continue
        charge = L.charge_of_enrollment(other)
        if charge is not None:
            charges.append(charge)
    charges.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for charge in charges:
        recompute_charge(charge)


def recompute_charge_of(enrollment):
    charge = L.charge_of_enrollment(enrollment)
    if charge is not None:
        recompute_charge(charge)
    return charge


# ---------------------------------------------------------------------------
# funding movements
# ---------------------------------------------------------------------------

def refresh_source_status(source):
    if source["status"] == "OPEN" and source["available_cents"] == calc.FUNDING_EXHAUSTED_AT_AVAILABLE_CENTS:
        source["status"] = "EXHAUSTED"
        touch(source)
        lapse_proposed_awards(source)
    elif source["status"] == "EXHAUSTED" and source["available_cents"] > calc.FUNDING_EXHAUSTED_AT_AVAILABLE_CENTS:
        source["status"] = "OPEN"
        touch(source)
    return source


def lapse_proposed_awards(source):
    for award in L.awards_of_source(source):
        if award["status"] != "PROPOSED":
            continue
        award["status"] = "LAPSED_NO_FUNDS"
        touch(award)
        enrollment = L.enrollment_of_award(award)
        if enrollment is not None:
            mark_unfunded(enrollment)


def mark_unfunded(enrollment):
    if enrollment["funding_status"] != "QUOTED":
        return
    awards = L.awards_of_enrollment(enrollment)
    if any(a["status"] not in ("LAPSED_NO_FUNDS", "RELEASED") for a in awards):
        return
    enrollment["funding_status"] = "UNFUNDED"
    touch(enrollment)
    demote_if_subsidy_required(enrollment)


def demote_if_subsidy_required(enrollment):
    """CASCADE A hop 8 / CASCADE F hop 4.  Waitlist promotion is deliberately
    NOT run for the slot this frees -- that pin is what makes the cascade
    terminate rather than oscillate."""
    if enrollment["enrollment_status"] != "CONFIRMED":
        return
    participant = L.participant_of_enrollment(enrollment)
    if participant is None or participant["income_band"] not in calc.SUBSIDY_REQUIRED_INCOME_BANDS:
        return
    enrollment["enrollment_status"] = "WAITLISTED"
    session = L.session_of_enrollment(enrollment)
    if session is not None:
        refresh_session_counters(session)
    enrollment["waitlist_score"] = calc.waitlist_priority_score(enrollment)
    touch(enrollment)


def encumber_award(award, silent=False):
    """PROPOSED -> ENCUMBERED.  When ``silent`` the unmet-precondition case is
    skipped rather than raised (PRD 2.12: a cascade hop whose preconditions are
    unmet is skipped silently)."""
    source = L.source_of_award(award)
    period = L.period_of_source(source)
    if silent:
        if award["status"] != "PROPOSED":
            return False
        if source is None or source["status"] == "CLOSED":
            return False
        if period is None or period["status"] != "OPEN":
            return False
        if source["available_cents"] < award["amount_cents"]:
            return False
    amount = award["amount_cents"]
    award["encumbered_cents"] = amount
    award["status"] = "ENCUMBERED"
    touch(award)
    source["available_cents"] -= amount
    source["encumbered_cents"] += amount
    touch(source)
    refresh_source_status(source)
    enrollment = L.enrollment_of_award(award)
    if enrollment is not None:
        if enrollment["funding_status"] == "QUOTED":
            enrollment["funding_status"] = "ENCUMBERED"
            touch(enrollment)
        recompute_charge_of(enrollment)
    return True


def release_award(award, force_released=False):
    source = L.source_of_award(award)
    release_cents = calc.encumbrance_release_cents(award)
    if award["status"] == "ENCUMBERED":
        award["encumbered_cents"] = 0
    elif award["status"] == "PARTIALLY_DISBURSED":
        award["encumbered_cents"] = award["disbursed_cents"]
    award["status"] = "RELEASED"
    touch(award)
    if release_cents and source is not None:
        source["encumbered_cents"] -= release_cents
        source["available_cents"] += release_cents
        touch(source)
        refresh_source_status(source)
    enrollment = L.enrollment_of_award(award)
    if enrollment is not None:
        if enrollment["funding_status"] == "ENCUMBERED" or force_released:
            if enrollment["funding_status"] != "RELEASED":
                enrollment["funding_status"] = "RELEASED"
                touch(enrollment)
        recompute_charge_of(enrollment)
    return award


# ---------------------------------------------------------------------------
# the six ordered sub-gates (ladder rungs 33, 34, 35, 37, 45, 46, 49, 50, 51,
# 54, 55, 60 -- visited in exactly that numeric sequence)
# ---------------------------------------------------------------------------

class GateFailure(Exception):
    def __init__(self, error_id):
        super(GateFailure, self).__init__(error_id)
        self.error_id = error_id


def _walk_sub_gates(enrollment, on_full):
    """Returns the routing decision (None, 'WAITLIST' or 'DENY').
    Raises GateFailure for every rung that is not routed."""
    session = L.session_of_enrollment(enrollment)
    program = L.program_of_session(session)
    participant = L.participant_of_enrollment(enrollment)
    session_date = date_of_instant(session["start_at"])
    routed = None

    # 33 -- participant active
    if participant["status"] != "ACTIVE":
        raise GateFailure("ERR_PARTICIPANT_NOT_ACTIVE")

    # 34 / 35 -- sub-gate A (consent)
    required_consents = program.get("required_consent_types") or []
    signed_by_type = {}
    for consent in L.consents_of_participant(participant):
        if consent["status"] == "SIGNED":
            signed_by_type.setdefault(consent["consent_type"], []).append(consent)
    for wanted in required_consents:
        if wanted not in signed_by_type:
            raise GateFailure("ERR_REQUIRED_CONSENT_MISSING")
    for wanted in required_consents:
        rows = signed_by_type.get(wanted, [])
        if not any(parse_date(c["expires_on"]) >= session_date for c in rows):
            raise GateFailure("ERR_CONSENT_EXPIRED")

    # 37 -- sub-gate B (assessment)
    if calc.assessment_gate_blocked(participant, session_date):
        raise GateFailure("ERR_ASSESSMENT_STALE")

    # 45 / 46 -- sub-gate C (capacity); the only rungs `on_full` may route
    if session["slots_available"] < 1:
        if on_full in ("WAITLIST", "DENY"):
            routed = on_full
        else:
            raise GateFailure("ERR_SESSION_FULL")
    if enrollment.get("effective_support_tier_at_session") == "ONE_TO_ONE":
        if session["one_to_one_available"] < 1:
            if on_full in ("WAITLIST", "DENY"):
                routed = on_full
            else:
                raise GateFailure("ERR_ONE_TO_ONE_POOL_EXHAUSTED")

    # 49 / 50 / 51 -- sub-gate D (equipment)
    if program.get("required_equipment_model_code") is not None:
        live = [
            r for r in L.reservations_of_enrollment(enrollment) if r["status"] in LIVE_RESERVATION
        ]
        for reservation in live:
            item = L.item_of_reservation(reservation)
            if item is None or not calc.equipment_fit_ok(item, program, participant):
                raise GateFailure("ERR_EQUIPMENT_FIT_MISMATCH")
        for reservation in live:
            item = L.item_of_reservation(reservation)
            if item is None or not calc.equipment_condition_ok(item, session):
                raise GateFailure("ERR_EQUIPMENT_INSPECTION_OVERDUE")
        if not live:
            raise GateFailure("ERR_EQUIPMENT_UNAVAILABLE")

    # 54 / 55 -- sub-gate E (transport)
    if enrollment.get("transport_requested"):
        already = False
        for booking in L.bookings_of_enrollment(enrollment):
            if booking["status"] not in LIVE_BOOKING:
                continue
            run = L.run_of_booking(booking)
            if run is not None and run["session_id"] == session["id"]:
                already = True
                break
        if not already:
            runs = L.runs_of_session(session)
            if participant["mobility_profile"] == "WHEELCHAIR":
                if not any(r["accessible_available"] >= 1 for r in runs):
                    raise GateFailure("ERR_ACCESSIBLE_POSITIONS_FULL")
            else:
                if not any(r["ambulatory_available"] >= 1 for r in runs):
                    raise GateFailure("ERR_AMBULATORY_SEATS_FULL")

    # 60 -- sub-gate F, last rung of the ladder
    if calc.financial_gate_blocked(participant):
        raise GateFailure("ERR_FAMILY_BALANCE_OUTSTANDING")

    return routed


def confirm_gate(enrollment, on_full):
    try:
        return _walk_sub_gates(enrollment, on_full)
    except GateFailure as failure:
        raise ApiError(failure.error_id)


def promotion_gate_ok(enrollment):
    try:
        _walk_sub_gates(enrollment, "ERROR")
    except GateFailure:
        return False
    return True


# ---------------------------------------------------------------------------
# confirmation, promotion, demotion
# ---------------------------------------------------------------------------

def apply_confirmation(enrollment, promoted=False):
    session = L.session_of_enrollment(enrollment)
    enrollment["enrollment_status"] = "CONFIRMED"
    if promoted:
        enrollment["promoted_at"] = db.clock_raw
    refresh_session_counters(session)
    for award in L.awards_of_enrollment(enrollment):
        if award["status"] == "PROPOSED":
            encumber_award(award, silent=True)
    recompute_charge_of(enrollment)
    household_sweep(enrollment)
    for booking in L.bookings_of_enrollment(enrollment):
        if booking["status"] == "RESERVED":
            booking["status"] = "CONFIRMED"
            touch(booking)
    touch(enrollment)
    return enrollment


def run_one_promotion(session):
    """At most one promotion per released slot."""
    for candidate in calc.promotion_candidates(session):
        if promotion_gate_ok(candidate):
            apply_confirmation(candidate, promoted=True)
            return candidate
    return None


# ---------------------------------------------------------------------------
# CASCADE A -- enrolment withdrawal, eight hops
# ---------------------------------------------------------------------------

def cancel_booking(booking, recompute=True):
    booking["status"] = "CANCELLED"
    touch(booking)
    run = L.run_of_booking(booking)
    if run is not None:
        refresh_run_counters(run)
        refresh_run_status(run)
    if recompute:
        recompute_charge_of(L.enrollment_of_booking(booking))
    return booking


def withdraw_enrollment(enrollment, run_promotion=True):
    previous = enrollment["enrollment_status"]
    session = L.session_of_enrollment(enrollment)
    enrollment["enrollment_status"] = "WITHDRAWN"
    touch(enrollment)

    if previous == "CONFIRMED":
        refresh_session_counters(session)
        for reservation in L.reservations_of_enrollment(enrollment):
            if reservation["status"] in LIVE_RESERVATION:
                reservation["status"] = "RELEASED"
                touch(reservation)
                item = L.item_of_reservation(reservation)
                if item is not None:
                    refresh_item_counters(item)
        for booking in L.bookings_of_enrollment(enrollment):
            if booking["status"] in ("RESERVED", "CONFIRMED"):
                cancel_booking(booking, recompute=False)
        for assignment in L.assignments_of_session(session):
            if (
                assignment["assignment_role"] == "ONE_TO_ONE"
                and assignment.get("dedicated_participant_id") == enrollment["participant_id"]
                and assignment["status"] in ("PROPOSED", "CONFIRMED", "LAPSED")
            ):
                assignment["status"] = "WITHDRAWN"
                touch(assignment)
        refresh_session_counters(session)
        for award in L.awards_of_enrollment(enrollment):
            if award["status"] in ("PROPOSED", "ENCUMBERED", "PARTIALLY_DISBURSED"):
                release_award(award, force_released=True)
    else:
        for award in L.awards_of_enrollment(enrollment):
            if award["status"] in ("PROPOSED", "ENCUMBERED"):
                release_award(award)

    recompute_charge_of(enrollment)

    if previous == "CONFIRMED":
        household_sweep(enrollment)
        if run_promotion:
            run_one_promotion(session)
    return enrollment


# ---------------------------------------------------------------------------
# CASCADE B -- session cancellation
# ---------------------------------------------------------------------------

def cancel_session(session):
    previous = session["status"]
    session["status"] = "CANCELLED"
    touch(session)
    if previous not in ("OPEN", "STAFFING_LOCKED"):
        return session

    touched_enrollments = []
    for enrollment in L.enrollments_of_session(session):
        if enrollment["enrollment_status"] not in LIVE_ENROLLMENT:
            continue
        enrollment["enrollment_status"] = "WITHDRAWN"
        touch(enrollment)
        touched_enrollments.append(enrollment)
        for booking in L.bookings_of_enrollment(enrollment):
            if booking["status"] in ("RESERVED", "CONFIRMED"):
                booking["status"] = "CANCELLED"
                touch(booking)

    refresh_session_counters(session)
    for run in L.runs_of_session(session):
        refresh_run_counters(run)
        refresh_run_status(run)
    for run in L.runs_of_session(session):
        if run["status"] in ("PLANNED", "BOARDING_FULL"):
            run["status"] = "CANCELLED"
            touch(run)
    for enrollment in touched_enrollments:
        recompute_charge_of(enrollment)

    if previous == "STAFFING_LOCKED":
        for assignment in L.assignments_of_session(session):
            if assignment["status"] in ("PROPOSED", "CONFIRMED", "LAPSED"):
                assignment["status"] = "WITHDRAWN"
                touch(assignment)
    return session


# ---------------------------------------------------------------------------
# CASCADE C -- the certification cliff
# ---------------------------------------------------------------------------

def cascade_certification_expiry(certification):
    lapsed = 0
    unlocked = 0
    affected = []
    for assignment in L.assignments_of_staff(certification["staff_member_id"]):
        if assignment["status"] != "CONFIRMED":
            continue
        session = db.get("program_sessions", assignment["session_id"])
        if session is None or session["status"] not in ("OPEN", "STAFFING_LOCKED"):
            continue
        program = L.program_of_session(session)
        required = (program.get("required_certification_types") or []) if program else []
        if certification["certification_type"] not in required:
            continue
        assignment["status"] = "LAPSED"
        assignment["qualified_at_session_date"] = False
        touch(assignment)
        lapsed += 1
        if all(s["id"] != session["id"] for s in affected):
            affected.append(session)

    for session in affected:
        refresh_session_counters(session)
        if session["status"] == "STAFFING_LOCKED" and session["staffing_gap"] > 0:
            if session["unlock_count"] < calc.MAX_SESSION_UNLOCKS:
                session["status"] = "OPEN"
                session["unlock_count"] += 1
                touch(session)
                unlocked += 1
    return lapsed, unlocked


# ---------------------------------------------------------------------------
# CASCADE D -- equipment condition
# ---------------------------------------------------------------------------

def apply_item_condition(item, new_status):
    previous = item["condition_status"]
    item["condition_status"] = new_status
    touch(item)
    if new_status in ("OUT_OF_SERVICE", "RETIRED") and previous in (
        "SERVICEABLE",
        "INSPECTION_DUE",
    ):
        for reservation in L.reservations_of_item(item):
            if reservation["status"] == "HELD":
                reservation["status"] = "VOIDED_INSPECTION_FAIL"
                touch(reservation)
        refresh_item_counters(item)
    return item


# ---------------------------------------------------------------------------
# CASCADE E -- participant exit
# ---------------------------------------------------------------------------

def exit_participant(participant):
    participant["status"] = "EXITED"
    touch(participant)
    for goal in L.goals_of_participant(participant):
        if goal["status"] in ("ACTIVE", "MASTERED"):
            goal["status"] = "DISCONTINUED"
            touch(goal)
    clock = db.clock_dt
    for enrollment in L.enrollments_of_participant(participant):
        if enrollment["enrollment_status"] not in LIVE_ENROLLMENT:
            continue
        session = L.session_of_enrollment(enrollment)
        start = parse_instant(session["start_at"]) if session else None
        if start is not None and start > clock:
            withdraw_enrollment(enrollment)
    return participant


# ---------------------------------------------------------------------------
# CASCADE F -- period close
# ---------------------------------------------------------------------------

def close_period(period):
    period["status"] = "CLOSED"
    touch(period)
    for source in L.sources_of_period(period):
        if source["status"] in ("OPEN", "EXHAUSTED"):
            source["status"] = "CLOSED"
            touch(source)
            lapse_proposed_awards(source)
    return period


# ---------------------------------------------------------------------------
# support-assessment activation and session delivery
# ---------------------------------------------------------------------------

def activate_assessment(assessment, participant):
    assessment["status"] = "ACTIVE"
    touch(assessment)
    for other in L.assessments_of_participant(participant):
        if other["id"] != assessment["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    participant["effective_support_tier"] = assessment["support_tier"]
    touch(participant)

    effective_from = parse_instant(assessment["effective_from"])
    sessions = []
    for enrollment in L.enrollments_of_participant(participant):
        session = L.session_of_enrollment(enrollment)
        if session is None or session["status"] not in ("DRAFT", "OPEN", "STAFFING_LOCKED"):
            continue
        start = parse_instant(session["start_at"])
        if start is None or effective_from is None or start < effective_from:
            continue
        enrollment["effective_support_tier_at_session"] = calc.effective_support_tier(
            participant, session
        )
        if all(s["id"] != session["id"] for s in sessions):
            sessions.append(session)
    for session in sessions:
        refresh_session_counters(session)
    return assessment


def deliver_session(session):
    session["status"] = "DELIVERED"
    for enrollment in L.enrollments_of_session(session):
        if enrollment["enrollment_status"] == "CONFIRMED":
            enrollment["enrollment_status"] = "NO_SHOW"
            touch(enrollment)
            for booking in L.bookings_of_enrollment(enrollment):
                if booking["status"] == "CONFIRMED":
                    booking["status"] = "NO_SHOW"
                    touch(booking)
                    run = L.run_of_booking(booking)
                    if run is not None:
                        refresh_run_counters(run)
                        refresh_run_status(run)

    participants = {}
    for enrollment in L.enrollments_of_session(session):
        participant = L.participant_of_enrollment(enrollment)
        if participant is None:
            continue
        participants[enrollment["id"]] = participant
        enrollment["effective_support_tier_at_session"] = calc.effective_support_tier(
            participant, session
        )

    session["required_group_staff_delivered"] = calc.required_group_staff_count(
        session, "ATTENDED"
    )
    for assignment in L.assignments_of_session(session):
        if assignment["status"] == "CONFIRMED":
            assignment["status"] = "DELIVERED"
            touch(assignment)
    for enrollment in L.enrollments_of_session(session):
        if enrollment["enrollment_status"] == "ATTENDED":
            charge = L.charge_of_enrollment(enrollment)
            if charge is not None:
                charge["status"] = calc.settlement_status(enrollment, charge["balance_cents"])
                touch(charge)
    refresh_session_counters(session)
    return session


# ---------------------------------------------------------------------------
# the epoch checkpoint (PRD 2.4)
# ---------------------------------------------------------------------------

def set_logical_clock(new_raw):
    new_dt = parse_instant(new_raw)
    new_date = new_dt.date()
    db.clock_raw = new_raw

    counters = {
        "consents_expired": 0,
        "certifications_expired": 0,
        "assignments_lapsed": 0,
        "sessions_unlocked": 0,
        "items_inspection_due": 0,
    }

    for consent in db.rows("consents"):
        expires = parse_date(consent["expires_on"])
        if consent["status"] == "SIGNED" and expires is not None and expires < new_date:
            consent["status"] = "EXPIRED"
            touch(consent)
            counters["consents_expired"] += 1

    for certification in db.rows("staff_certifications"):
        expires = parse_date(certification["expires_on"])
        if certification["status"] == "VALID" and expires is not None and expires < new_date:
            certification["status"] = "EXPIRED"
            touch(certification)
            counters["certifications_expired"] += 1
            lapsed, unlocked = cascade_certification_expiry(certification)
            counters["assignments_lapsed"] += lapsed
            counters["sessions_unlocked"] += unlocked

    for item in db.rows("equipment_items"):
        if item["item_kind"] != "SERIALIZED":
            continue
        due = parse_date(item.get("inspection_due_date"))
        if item["condition_status"] == "SERVICEABLE" and due is not None and due < new_date:
            item["condition_status"] = "INSPECTION_DUE"
            touch(item)
            counters["items_inspection_due"] += 1

    return counters


def next_inspection_due_date():
    return render_date(add_days(db.clock_date, calc.INSPECTION_INTERVAL_DAYS))


def peek_staffing_gap(session):
    """The recomputed gap, without persisting anything -- so a rung that reads
    it and then fails leaves no mutation behind."""
    assignments = L.assignments_of_session(session)
    group = len(
        [
            a
            for a in assignments
            if a["assignment_role"] in ("LEAD", "GROUP") and a["status"] in LIVE_ASSIGNMENT
        ]
    )
    one_to_one_staffed = len(
        [
            a
            for a in assignments
            if a["assignment_role"] == "ONE_TO_ONE" and a["status"] in LIVE_ASSIGNMENT
        ]
    )
    confirmed = [
        e for e in L.enrollments_of_session(session) if e["enrollment_status"] == "CONFIRMED"
    ]
    one_to_one_committed = len(
        [e for e in confirmed if e.get("effective_support_tier_at_session") == "ONE_TO_ONE"]
    )
    planned = calc.required_group_staff_count(session, "CONFIRMED")
    return max(0, planned - group) + max(0, one_to_one_committed - one_to_one_staffed)
