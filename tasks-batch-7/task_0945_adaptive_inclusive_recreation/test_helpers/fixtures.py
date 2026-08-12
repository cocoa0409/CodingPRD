"""Composite setup helpers.

Every helper builds its state through declared endpoints only — the server
seeds nothing and the harness wipes all state before each test.  Setup calls
use the lenient validator so a broken precondition reports "Setup failed"
rather than a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    activity_program_payload,
    caregiver_payload,
    consent_payload,
    equipment_item_payload,
    fee_scale_band_payload,
    funding_source_payload,
    goal_payload,
    operating_period_payload,
    participant_payload,
    program_session_payload,
    staff_assignment_payload,
    staff_certification_payload,
    staff_member_payload,
    support_assessment_payload,
    transport_run_payload,
)
from .test_users import (
    OFFICER_ONE_USER_ID,
    OFFICER_TWO_USER_ID,
    TEST_USERS,
    make_activity_lead_headers,
    make_caregiver_headers,
    make_funding_officer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]
OFFICER = TEST_USERS["funding_officer_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Move the logical clock and run the epoch checkpoint."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def create_fee_band(**overrides):
    return get_success_data(api.create_fee_scale_band(fee_scale_band_payload(**overrides), ADMIN))


def create_period(**overrides):
    return get_success_data(api.create_operating_period(operating_period_payload(**overrides), ADMIN))


def move_posture(period_id, target_status):
    return get_success_data(
        api.set_period_posture(period_id, {"target_status": target_status}, ADMIN)
    )


def create_program(**overrides):
    return get_success_data(api.create_activity_program(activity_program_payload(**overrides), ADMIN))


def create_session(program_id, **overrides):
    return get_success_data(
        api.create_program_session(program_session_payload(program_id, **overrides), ADMIN)
    )


def open_session(session_id):
    return get_success_data(api.open_session(session_id, ADMIN))


def read_session(session_id):
    return get_success_data(api.get_program_session(session_id, ADMIN))


def session_version(session_id):
    return read_session(session_id)["version"]


def staffing_summary(session_id):
    return get_success_data(api.get_staffing_summary(session_id, ADMIN))


def create_open_session(program_id=None, program_overrides=None, **session_overrides):
    """Programme (created unless one is named) + one OPEN session.

    Returns (program, session).
    """
    if program_id is None:
        program = create_program(**(program_overrides or {}))
        program_id = program["id"]
    else:
        program = get_success_data(api.get_activity_program(program_id, ADMIN))
    session = create_session(program_id, **session_overrides)
    open_session(session["id"])
    return program, read_session(session["id"])


# --------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------
def create_participant(**overrides):
    return get_success_data(api.create_participant(participant_payload(**overrides), COORD))


def read_participant(participant_id):
    return get_success_data(api.get_participant(participant_id, COORD))


def participant_version(participant_id):
    return read_participant(participant_id)["version"]


def create_assessment(participant_id, expected_participant_version=None, **overrides):
    if expected_participant_version is None:
        expected_participant_version = participant_version(participant_id)
    payload = support_assessment_payload(
        participant_id, expected_participant_version, **overrides
    )
    return get_success_data(api.create_support_assessment(payload, COORD))


def activate_assessment(assessment_id):
    return get_success_data(api.activate_support_assessment(assessment_id, COORD))


def set_participant_status(participant_id, target_status):
    return get_success_data(
        api.set_participant_status(participant_id, {"target_status": target_status}, COORD)
    )


def create_active_participant(support_tier="INDEPENDENT", assessment_overrides=None, **overrides):
    """Participant + DRAFT assessment + activation + ACTIVE status.

    Returns {"participant": ..., "assessment": ...} with the participant read
    back after every bump so its version is current.
    """
    participant = create_participant(**overrides)
    assessment = create_assessment(
        participant["id"], support_tier=support_tier, **(assessment_overrides or {})
    )
    assessment = activate_assessment(assessment["id"])
    set_participant_status(participant["id"], "ACTIVE")
    return {"participant": read_participant(participant["id"]), "assessment": assessment}


def create_caregiver(participant_id, **overrides):
    return get_success_data(
        api.create_caregiver(caregiver_payload(participant_id, **overrides), COORD)
    )


def create_consent(participant_id, **overrides):
    return get_success_data(api.create_consent(consent_payload(participant_id, **overrides), COORD))


def sign_consent_as_guardian(consent_id, caregiver_id):
    return get_success_data(
        api.sign_consent(
            consent_id, {"signed_by_caregiver_id": caregiver_id},
            make_caregiver_headers(caregiver_id),
        )
    )


def create_signed_consent(participant_id, caregiver_id, **overrides):
    consent = create_consent(participant_id, **overrides)
    return sign_consent_as_guardian(consent["id"], caregiver_id)


# --------------------------------------------------------------------------
# Enrolment
# --------------------------------------------------------------------------
def request_enrollment(participant_id, session_id, expected_session_version=None, **extra):
    """Create an enrolment, echoing the session's current version by default."""
    if expected_session_version is None:
        expected_session_version = session_version(session_id)
    payload = {
        "participant_id": participant_id,
        "session_id": session_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(extra)
    return get_success_data(api.create_enrollment(payload, COORD))


def confirm_enrollment(enrollment_id, on_full=None):
    payload = {} if on_full is None else {"on_full": on_full}
    return get_success_data(api.confirm_enrollment(enrollment_id, COORD, payload))


def withdraw_enrollment(enrollment_id, headers=None):
    return get_success_data(api.withdraw_enrollment(enrollment_id, headers or COORD))


def read_enrollment(enrollment_id):
    return get_success_data(api.get_enrollment(enrollment_id, COORD))


def create_confirmed_enrollment(participant_id, session_id, **extra):
    enrollment = request_enrollment(participant_id, session_id, **extra)
    return confirm_enrollment(enrollment["id"])


def charge_for(enrollment_id):
    """The enrolment charge is discoverable only through the filtered list read."""
    data = get_success_data(
        api.list_enrollment_charges(OFFICER, params={"enrollment_id": enrollment_id})
    )
    assert len(data) == 1, f"expected exactly one charge for enrolment {enrollment_id}, got {len(data)}"
    return data[0]


def record_payment(charge_id, amount_cents):
    return get_success_data(api.record_payment(charge_id, {"amount_cents": amount_cents}, OFFICER))


# --------------------------------------------------------------------------
# Staffing
# --------------------------------------------------------------------------
def create_staff(**overrides):
    return get_success_data(api.create_staff_member(staff_member_payload(**overrides), ADMIN))


def create_certification(staff_member_id, **overrides):
    return get_success_data(
        api.create_staff_certification(
            staff_certification_payload(staff_member_id, **overrides), ADMIN
        )
    )


def propose_assignment(session_id, staff_member_id, **overrides):
    return get_success_data(
        api.create_staff_assignment(
            staff_assignment_payload(session_id, staff_member_id, **overrides), ADMIN
        )
    )


def confirm_assignment(assignment_id, staff_member_id):
    return get_success_data(
        api.confirm_assignment(assignment_id, make_activity_lead_headers(staff_member_id))
    )


def read_assignment(assignment_id):
    return get_success_data(api.get_staff_assignment(assignment_id, ADMIN))


def lock_staffing(session_id, staff_member_id):
    return get_success_data(
        api.lock_staffing(session_id, make_activity_lead_headers(staff_member_id))
    )


def unlock_staffing(session_id, staff_member_id):
    return get_success_data(
        api.unlock_staffing(session_id, make_activity_lead_headers(staff_member_id))
    )


def deliver_session(session_id, staff_member_id):
    return get_success_data(
        api.deliver_session(session_id, make_activity_lead_headers(staff_member_id))
    )


def cancel_session(session_id):
    return get_success_data(api.cancel_session(session_id, ADMIN))


def record_attendance(enrollment_id, staff_member_id, outcome):
    return get_success_data(
        api.record_attendance(
            enrollment_id, {"outcome": outcome}, make_activity_lead_headers(staff_member_id)
        )
    )


def setup_staffed_locked_session(session_id, staff_member_id=None, assignment_role="GROUP"):
    """Propose one assignment on the session and lock its staffing.

    Returns {"staff": ..., "assignment": ..., "session": ...}.
    """
    if staff_member_id is None:
        staff_member_id = create_staff()["id"]
    assignment = propose_assignment(session_id, staff_member_id, assignment_role=assignment_role)
    session = lock_staffing(session_id, staff_member_id)
    return {"staff_id": staff_member_id, "assignment": assignment, "session": session}


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------
def create_equipment_item(**overrides):
    return get_success_data(api.create_equipment_item(equipment_item_payload(**overrides), ADMIN))


def read_equipment_item(item_id):
    return get_success_data(api.get_equipment_item(item_id, ADMIN))


def item_version(item_id):
    return read_equipment_item(item_id)["version"]


def reserve_equipment(enrollment_id, equipment_item_id, expected_item_version=None):
    if expected_item_version is None:
        expected_item_version = item_version(equipment_item_id)
    payload = {
        "enrollment_id": enrollment_id,
        "equipment_item_id": equipment_item_id,
        "expected_item_version": expected_item_version,
    }
    return get_success_data(api.create_equipment_reservation(payload, COORD))


def read_reservation(reservation_id):
    return get_success_data(api.get_equipment_reservation(reservation_id, ADMIN))


def record_inspection(item_id, disposition):
    return get_success_data(api.record_inspection(item_id, {"disposition": disposition}, ADMIN))


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------
def create_transport_run(session_id, **overrides):
    return get_success_data(
        api.create_transport_run(transport_run_payload(session_id, **overrides), DISPATCH)
    )


def read_transport_run(run_id):
    return get_success_data(api.get_transport_run(run_id, DISPATCH))


def run_version(run_id):
    return read_transport_run(run_id)["version"]


def book_position(transport_run_id, enrollment_id, position_type, expected_run_version=None):
    if expected_run_version is None:
        expected_run_version = run_version(transport_run_id)
    payload = {
        "transport_run_id": transport_run_id,
        "enrollment_id": enrollment_id,
        "position_type": position_type,
        "expected_run_version": expected_run_version,
    }
    return get_success_data(api.create_transport_booking(payload, DISPATCH))


def read_booking(booking_id):
    return get_success_data(api.get_transport_booking(booking_id, DISPATCH))


# --------------------------------------------------------------------------
# Funding
# --------------------------------------------------------------------------
def create_funding_source(operating_period_id, officer_id=OFFICER_ONE_USER_ID, **overrides):
    return get_success_data(
        api.create_funding_source(
            funding_source_payload(operating_period_id, **overrides),
            make_funding_officer_headers(officer_id),
        )
    )


def read_funding_source(source_id):
    return get_success_data(api.get_funding_source(source_id, OFFICER))


def funding_source_version(source_id):
    return read_funding_source(source_id)["version"]


def create_award(
    enrollment_id,
    funding_source_id=None,
    expected_funding_source_version=None,
    officer_id=OFFICER_ONE_USER_ID,
    **extra,
):
    payload = {"enrollment_id": enrollment_id}
    if funding_source_id is not None:
        payload["funding_source_id"] = funding_source_id
        if expected_funding_source_version is None:
            expected_funding_source_version = funding_source_version(funding_source_id)
        payload["expected_funding_source_version"] = expected_funding_source_version
    elif expected_funding_source_version is not None:
        payload["expected_funding_source_version"] = expected_funding_source_version
    payload.update(extra)
    return get_success_data(
        api.create_scholarship_award(payload, make_funding_officer_headers(officer_id))
    )


def read_award(award_id):
    return get_success_data(api.get_scholarship_award(award_id, OFFICER))


def encumber_award(award_id, officer_id=OFFICER_TWO_USER_ID):
    return get_success_data(
        api.encumber_award(award_id, make_funding_officer_headers(officer_id))
    )


def disburse_award(award_id, amount_cents, officer_id=OFFICER_TWO_USER_ID):
    return get_success_data(
        api.disburse_award(
            award_id, {"amount_cents": amount_cents}, make_funding_officer_headers(officer_id)
        )
    )


def release_award(award_id, officer_id=OFFICER_TWO_USER_ID):
    return get_success_data(api.release_award(award_id, make_funding_officer_headers(officer_id)))


# --------------------------------------------------------------------------
# Goals
# --------------------------------------------------------------------------
def create_goal(participant_id, **overrides):
    return get_success_data(api.create_goal(goal_payload(participant_id, **overrides), COORD))


def read_goal(goal_id):
    return get_success_data(api.get_goal(goal_id, COORD))


def rate_goal(goal_id, session_id, score, staff_member_id, note=""):
    payload = {"session_id": session_id, "score": score, "note": note}
    return get_success_data(
        api.create_goal_rating(goal_id, payload, make_activity_lead_headers(staff_member_id))
    )


# --------------------------------------------------------------------------
# Higher-tier composites
# --------------------------------------------------------------------------
def setup_attended_session(
    program_overrides=None,
    session_overrides=None,
    participant_overrides=None,
    support_tier="INDEPENDENT",
    band_overrides=None,
    outcome="ATTENDED",
):
    """Band + programme + OPEN session + one CONFIRMED participant + staffing
    locked + clock moved into the session + attendance recorded.

    Returns a dict of every row the caller may need.
    """
    create_fee_band(**(band_overrides or {}))
    program, session = create_open_session(
        program_overrides=program_overrides, **(session_overrides or {})
    )
    who = create_active_participant(support_tier=support_tier, **(participant_overrides or {}))
    enrollment = create_confirmed_enrollment(who["participant"]["id"], session["id"])
    staff_id = create_staff()["id"]
    propose_assignment(session["id"], staff_id)
    lock_staffing(session["id"], staff_id)
    session = read_session(session["id"])
    set_clock(_midpoint_iso(session["start_at"], session["end_at"]))
    enrollment = record_attendance(enrollment["id"], staff_id, outcome)
    return {
        "program": program,
        "session": read_session(session["id"]),
        "participant": who["participant"],
        "assessment": who["assessment"],
        "enrollment": enrollment,
        "staff_id": staff_id,
    }


def _midpoint_iso(start_at, end_at):
    """An instant between the session's start and end, for attendance."""
    from .assertions import parse_instant

    start = parse_instant(start_at)
    end = parse_instant(end_at)
    middle = start + (end - start) / 2
    return middle.strftime("%Y-%m-%dT%H:%M:%SZ")


def after_iso(instant, minutes=30):
    """An instant a fixed number of minutes after the supplied one."""
    from datetime import timedelta

    from .assertions import parse_instant

    return (parse_instant(instant) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
