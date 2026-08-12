"""Staffing a session by support need: requirements, certifications and locks."""

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_assessment,
    confirm_assignment,
    create_assessment,
    create_active_participant,
    create_certification,
    create_confirmed_enrollment,
    create_fee_band,
    create_open_session,
    create_program,
    create_session,
    create_staff,
    deliver_session,
    lock_staffing,
    propose_assignment,
    read_assignment,
    read_enrollment,
    read_participant,
    read_session,
    record_attendance,
    request_enrollment,
    set_clock,
    staffing_summary,
    unlock_staffing,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD
from test_helpers.test_users import make_activity_lead_headers


def _high_risk_session_with(tiers, slot_capacity=3, one_to_one_pool_size=0):
    """A HIGH-risk session with one CONFIRMED participant per requested tier."""
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Climbing",
            "activity_type": "SPORTS",
            "risk_tier": "HIGH",
        },
        slot_capacity=slot_capacity,
        one_to_one_pool_size=one_to_one_pool_size,
    )
    names = [
        ("Ada Rivera", "2010-03-04", "HH-1", 40),
        ("Ben Osei", "2009-07-15", "HH-2", 45),
        ("Cleo Vance", "2008-11-02", "HH-3", 50),
        ("Dara Kim", "2011-02-09", "HH-4", 38),
    ]
    enrollments = []
    for tier, (name, dob, household, weight) in zip(tiers, names):
        who = create_active_participant(
            support_tier=tier,
            legal_name=name, date_of_birth=dob, household_id=household, weight_kg=weight,
        )
        enrollments.append(
            create_confirmed_enrollment(who["participant"]["id"], session["id"])
        )
    return session, enrollments


def test_planned_staffing_requirement_is_two_for_three_substantial_participants():
    """PRD §3.5: "Otherwise sum the support points of the pooled participants,
    counting 25 for each `INDEPENDENT`, 50 for each `INTERMITTENT` and 100 for
    each `SUBSTANTIAL`. Multiply that sum by the programme's risk multiplier —
    10000 basis points for `LOW`, 12500 for `MODERATE`, 15000 for `HIGH` —
    divide by 10000, and **round the result up to a whole number of points**.
    Then divide those weighted points by the staff point capacity of 400 and
    **round up again**."
    PRD §3.5: "The `PLANNED` variant takes the enrolments whose
    `enrollment_status` is `CONFIRMED` — everyone expected — and is written to
    the session's `required_group_staff_planned` whenever the session is `DRAFT`,
    `OPEN` or `STAFFING_LOCKED`."

    Design: Difficulty/dual_variant_calc/staffing_requirement_planned_two_but_delivered_one
    """
    session, _enrollments = _high_risk_session_with(
        ["SUBSTANTIAL", "SUBSTANTIAL", "SUBSTANTIAL"]
    )

    summary = staffing_summary(session["id"])
    assert summary["pooled_support_points"] == 300
    assert summary["required_group_staff_planned"] == 2, (
        "300 points at HIGH risk is 450 weighted points, and ceil(450/400) is 2; "
        f"got {summary['required_group_staff_planned']}"
    )
    assert read_session(session["id"])["required_group_staff_planned"] == 2


def test_delivered_staffing_requirement_is_one_after_a_no_show():
    """PRD §3.5: "The `DELIVERED` variant takes the enrolments whose
    `enrollment_status` is `ATTENDED` — only those who actually turned up — and is
    written once, to `required_group_staff_delivered`, during the deliver
    transition."
    PRD §3.5: "Delivery does four things in order: every enrolment still sitting
    at `CONFIRMED` is moved to `NO_SHOW`, with the same transport-booking
    consequence a manually recorded no-show would have;
    `required_group_staff_delivered` is computed from the `DELIVERED` roster
    variant; every assignment on the session whose status is `CONFIRMED` moves to
    `DELIVERED`; and every charge on an `ATTENDED` enrolment is finalised by
    re-deriving its settlement `status`."

    Design: Difficulty/dual_variant_calc/staffing_requirement_planned_two_but_delivered_one
    """
    session, enrollments = _high_risk_session_with(
        ["SUBSTANTIAL", "SUBSTANTIAL", "SUBSTANTIAL"]
    )
    lead_id = create_staff(full_name="Dana Lead")["id"]
    aide_id = create_staff(full_name="Eli Support", role_title="Program Aide")["id"]
    propose_assignment(session["id"], lead_id, assignment_role="LEAD")
    propose_assignment(session["id"], aide_id, assignment_role="GROUP")

    assert staffing_summary(session["id"])["required_group_staff_planned"] == 2
    lock_staffing(session["id"], lead_id)

    set_clock("2026-06-10T15:00:00Z")
    record_attendance(enrollments[0]["id"], lead_id, "ATTENDED")
    record_attendance(enrollments[1]["id"], lead_id, "ATTENDED")
    set_clock("2026-06-10T16:30:00Z")

    delivered = deliver_session(session["id"], lead_id)

    assert delivered["status"] == "DELIVERED"
    assert delivered["required_group_staff_delivered"] == 1, (
        "200 attended points at HIGH risk is 300 weighted points, and ceil(300/400) is 1; "
        f"got {delivered['required_group_staff_delivered']}"
    )
    assert read_enrollment(enrollments[2]["id"])["enrollment_status"] == "NO_SHOW"
    assert read_enrollment(enrollments[0]["id"])["enrollment_status"] == "ATTENDED"
    assert read_enrollment(enrollments[1]["id"])["enrollment_status"] == "ATTENDED"


def test_staff_requirement_takes_both_ceilings_in_the_pinned_order():
    """PRD §3.5: "Multiply that sum by the programme's risk multiplier — 10000
    basis points for `LOW`, 12500 for `MODERATE`, 15000 for `HIGH` — divide by
    10000, and **round the result up to a whole number of points**. Then divide
    those weighted points by the staff point capacity of 400 and **round up
    again**. The requirement is the larger of that figure and 1. Both ceilings
    must be taken in that order; dividing first and ceiling once gives different
    answers on many inputs."

    Design: Difficulty/combinatorial_formula/staff_requirement_nested_ceilings_in_the_pinned_order
    """
    session, _enrollments = _high_risk_session_with(
        ["SUBSTANTIAL", "SUBSTANTIAL", "INTERMITTENT"]
    )

    summary = staffing_summary(session["id"])
    assert summary["pooled_support_points"] == 250
    assert summary["required_group_staff_planned"] == 1, (
        "ceil(ceil(250 * 1.5) / 400) is 1; ceiling the division first would give 2, "
        f"got {summary['required_group_staff_planned']}"
    )


def test_staffing_gap_counts_the_unstaffed_requirement_from_the_pinned_ceilings():
    """PRD §3.5: "The group shortfall is `required_group_staff_planned` minus
    `assigned_group_staff_count`, floored at 0; the one-to-one shortfall is
    `one_to_one_committed` minus `one_to_one_staffed`, also floored at 0; and
    `staffing_gap` is the two added together."
    PRD §3.5: "The requirement is the larger of that figure and 1. Both ceilings
    must be taken in that order; dividing first and ceiling once gives different
    answers on many inputs."

    Design: Difficulty/combinatorial_formula/staff_requirement_nested_ceilings_in_the_pinned_order
    """
    session, _enrollments = _high_risk_session_with(
        ["SUBSTANTIAL", "SUBSTANTIAL", "INTERMITTENT"]
    )

    summary = staffing_summary(session["id"])
    assert summary["staffing_gap"] == 1, (
        "one required group staffer and none assigned leaves a gap of 1; "
        f"got {summary['staffing_gap']}"
    )
    assert summary["assigned_group_staff_count"] == 0
    assert read_session(session["id"])["one_to_one_committed"] == 0


def test_empty_roster_requires_zero_group_staff():
    """PRD §3.5: "If the pooled set is empty, the requirement is exactly 0 — the
    one-staffer floor does **not** apply to an empty set, so a session attended
    only by one-to-one participants, or by nobody, needs no group staff at all."

    Design: Difficulty/boundary_precision_check/empty_roster_requires_zero_group_staff_not_the_minimum_of_one
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={"name": "Inclusive Yoga"}, slot_capacity=2
    )
    who = create_active_participant()
    request_enrollment(who["participant"]["id"], session["id"])

    summary = staffing_summary(session["id"])
    assert summary["pooled_support_points"] == 0
    assert summary["required_group_staff_planned"] == 0, (
        "a REQUESTED row is not on the planned roster, so the requirement is 0, not 1"
    )
    assert summary["staffing_gap"] == 0


def test_first_confirmation_lifts_the_requirement_from_zero_to_one():
    """PRD §3.5: "If the pooled set is empty, the requirement is exactly 0 — the
    one-staffer floor does **not** apply to an empty set, so a session attended
    only by one-to-one participants, or by nobody, needs no group staff at all."
    PRD §3.5: "The requirement is the larger of that figure and 1."

    Design: Difficulty/boundary_precision_check/empty_roster_requires_zero_group_staff_not_the_minimum_of_one
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={"name": "Inclusive Yoga"}, slot_capacity=2
    )
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    assert staffing_summary(session["id"])["required_group_staff_planned"] == 0

    validate_success(api_client.confirm_enrollment(enrollment["id"], COORD, {}))

    summary = staffing_summary(session["id"])
    assert summary["pooled_support_points"] == 25
    assert summary["required_group_staff_planned"] == 1, (
        "25 points at LOW risk is 25 weighted points, ceil(25/400) is 1 after the floor; "
        f"got {summary['required_group_staff_planned']}"
    )
    after = read_session(session["id"])
    assert after["slots_committed"] == 1
    assert after["slots_available"] == 1


def _session_locked_twice_over():
    """An empty session driven OPEN -> LOCKED -> OPEN -> LOCKED -> OPEN -> LOCKED,
    leaving unlock_count at 2."""
    _program, session = create_open_session(
        program_overrides={"name": "Community Outing", "activity_type": "COMMUNITY_OUTING"}
    )
    staff_id = create_staff()["id"]
    lock_staffing(session["id"], staff_id)
    unlock_staffing(session["id"], staff_id)
    lock_staffing(session["id"], staff_id)
    unlock_staffing(session["id"], staff_id)
    locked = lock_staffing(session["id"], staff_id)
    return session, staff_id, locked


def test_third_unlock_is_refused_with_unlock_limit_reached():
    """PRD §2.10 rung 48: "On staffing unlock, the session's `unlock_count` is
    below 2 — otherwise `ERR_UNLOCK_LIMIT_REACHED` (409)."
    PRD §3.5: "Unlocking returns a `STAFFING_LOCKED` session to `OPEN`, raises
    its `unlock_count` by one and its `version` by one, and is capped: the third
    attempt, made when `unlock_count` already equals 2, is refused with
    `ERR_UNLOCK_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/session_staffing_unlock_loop_stops_at_the_second_unlock
    """
    session, staff_id, locked = _session_locked_twice_over()
    assert locked["unlock_count"] == 2
    assert locked["status"] == "STAFFING_LOCKED"

    validate_error(
        api_client.unlock_staffing(session["id"], make_activity_lead_headers(staff_id)),
        ApiErrorId.ERR_UNLOCK_LIMIT_REACHED.value,
        expected_status=409,
    )


def test_the_refused_unlock_leaves_the_session_locked_with_unlock_count_two():
    """PRD §3.5: "Unlocking returns a `STAFFING_LOCKED` session to `OPEN`, raises
    its `unlock_count` by one and its `version` by one, and is capped: the third
    attempt, made when `unlock_count` already equals 2, is refused with
    `ERR_UNLOCK_LIMIT_REACHED`."
    PRD §2.10 rung 48: "On staffing unlock, the session's `unlock_count` is below
    2 — otherwise `ERR_UNLOCK_LIMIT_REACHED` (409)."

    Design: Difficulty/non_linear_state_machine/session_staffing_unlock_loop_stops_at_the_second_unlock
    """
    session, staff_id, _locked = _session_locked_twice_over()

    validate_error(
        api_client.unlock_staffing(session["id"], make_activity_lead_headers(staff_id)),
        ApiErrorId.ERR_UNLOCK_LIMIT_REACHED.value,
        expected_status=409,
    )

    after = read_session(session["id"])
    assert after["unlock_count"] == 2, "the refused attempt must not move the counter"
    assert after["status"] == "STAFFING_LOCKED"


def _two_staffers_proposed_on_a_cpr_session():
    """One staffer's CPR expires exactly on the session date, the other's the day
    before; both hold PROPOSED assignments on the 2026-06-10 session."""
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Aquatics",
            "activity_type": "AQUATICS",
            "required_certification_types": ["CPR"],
        }
    )
    edge_staff = create_staff(full_name="Dana Edge")["id"]
    create_certification(
        edge_staff, certification_type="CPR", issued_on="2024-06-10", expires_on="2026-06-10"
    )
    short_staff = create_staff(full_name="Eli Edge", role_title="Program Aide")["id"]
    create_certification(
        short_staff, certification_type="CPR", issued_on="2024-06-09", expires_on="2026-06-09"
    )
    edge_assignment = propose_assignment(session["id"], edge_staff)
    short_assignment = propose_assignment(session["id"], short_staff)
    return session, (edge_staff, edge_assignment), (short_staff, short_assignment)


def test_certification_expiring_exactly_on_the_session_date_confirms():
    """PRD §3.5: "Validity is inclusive: a certification whose `expires_on` equals
    the date being checked is still valid on that date."
    PRD §2.10 rung 41: "On assignment confirmation, assignment revalidation and
    staffing lock, every required certification has an `expires_on` on or after
    the **session's** date — otherwise `ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION`
    (422). This rung is deliberately not applied at assignment creation."

    Design: Difficulty/boundary_precision_check/certification_expiring_exactly_on_the_session_date_is_still_valid
    """
    _session, (edge_staff, edge_assignment), (_short_staff, short_assignment) = (
        _two_staffers_proposed_on_a_cpr_session()
    )

    assert edge_assignment["qualified_at_assignment"] is True
    assert short_assignment["qualified_at_assignment"] is True

    confirmed = confirm_assignment(edge_assignment["id"], edge_staff)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["qualified_at_session_date"] is True, (
        "a CPR certification expiring 2026-06-10 is valid for a 2026-06-10 session"
    )


def test_certification_expiring_the_day_before_the_session_is_refused_at_confirmation():
    """PRD §2.10 rung 41: "On assignment confirmation, assignment revalidation and
    staffing lock, every required certification has an `expires_on` on or after
    the **session's** date — otherwise `ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION`
    (422). This rung is deliberately not applied at assignment creation."
    PRD §3.5: "The `AT_SESSION_DATE` verdict uses the calendar date of the
    session's `start_at` and is stored as `qualified_at_session_date`; it is
    stamped at creation and recomputed at assignment confirmation, at
    revalidation, at staffing lock, and by the epoch checkpoint."

    Design: Difficulty/boundary_precision_check/certification_expiring_exactly_on_the_session_date_is_still_valid
    """
    _session, _edge, (short_staff, short_assignment) = _two_staffers_proposed_on_a_cpr_session()

    validate_error(
        api_client.confirm_assignment(
            short_assignment["id"], make_activity_lead_headers(short_staff)
        ),
        ApiErrorId.ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION.value,
        expected_status=422,
    )

    after = read_assignment(short_assignment["id"])
    assert after["status"] == "PROPOSED"
    assert after["qualified_at_session_date"] is False


def _three_same_day_sessions_and_one_busy_staffer():
    """Sessions X 09:00-11:00, Y 11:00-13:00 and Z 11:30-13:30, with a staffer
    already proposed on X."""
    program = create_program(scheduled_session_count=3)
    x = create_session(
        program["id"], start_at="2026-06-10T09:00:00Z", end_at="2026-06-10T11:00:00Z"
    )
    y = create_session(
        program["id"], start_at="2026-06-10T11:00:00Z", end_at="2026-06-10T13:00:00Z"
    )
    z = create_session(
        program["id"], start_at="2026-06-10T11:30:00Z", end_at="2026-06-10T13:30:00Z"
    )
    staff_id = create_staff()["id"]
    propose_assignment(x["id"], staff_id)
    return x, y, z, staff_id


def test_staff_back_to_back_sessions_collide_because_of_the_turnaround_buffer():
    """PRD §3.5: "And the staffer must be free: over that staffer's assignments
    whose `status` is `PROPOSED` or `CONFIRMED` on sessions whose `status` is
    `DRAFT`, `OPEN` or `STAFFING_LOCKED`, the proposal is rejected with
    `ERR_STAFF_TIME_CONFLICT` when the new session's `start_at` falls before the
    existing session's `end_at` extended by 30 minutes **and** the existing
    session's `start_at` falls before the new session's `end_at` extended by the
    same 30 minutes."
    PRD §3.5: "That half-hour turnaround buffer is applied to both ends, which
    means **back-to-back sessions do collide for staff** even though, as §3.3
    noted, they do not collide for participants — the two overlap rules are
    deliberately different."

    Design: Difficulty/resource_temporal_overlap/staff_back_to_back_sessions_collide_because_of_the_turnaround_buffer
    """
    _x, y, _z, staff_id = _three_same_day_sessions_and_one_busy_staffer()

    validate_error(
        api_client.create_staff_assignment(
            {"session_id": y["id"], "staff_member_id": staff_id, "assignment_role": "GROUP"},
            ADMIN,
        ),
        ApiErrorId.ERR_STAFF_TIME_CONFLICT.value,
        expected_status=409,
    )
    assert read_session(y["id"])["assigned_group_staff_count"] == 0


def test_staff_session_beyond_the_turnaround_buffer_is_accepted():
    """PRD §3.5: "the proposal is rejected with `ERR_STAFF_TIME_CONFLICT` when the
    new session's `start_at` falls before the existing session's `end_at`
    extended by 30 minutes **and** the existing session's `start_at` falls before
    the new session's `end_at` extended by the same 30 minutes."
    PRD §3.5: "A successful proposal files the row in `status` `PROPOSED`, stamps
    both qualification flags, recomputes the session's counters and
    `staffing_gap`, and raises the session's `version` by one."

    Design: Difficulty/resource_temporal_overlap/staff_back_to_back_sessions_collide_because_of_the_turnaround_buffer
    """
    _x, _y, z, staff_id = _three_same_day_sessions_and_one_busy_staffer()

    accepted = validate_success(
        api_client.create_staff_assignment(
            {"session_id": z["id"], "staff_member_id": staff_id, "assignment_role": "GROUP"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PROPOSED"
    assert read_session(z["id"])["assigned_group_staff_count"] == 1


def test_assignment_rungs_reject_missing_and_already_expired_certifications():
    """PRD §3.5: "The staffer must hold a certification row for every type the
    programme requires, or the proposal fails with `ERR_STAFF_CERT_MISSING`.
    Every one of those certifications must carry an `expires_on` on or after
    today's logical-clock date, or the proposal fails with
    `ERR_STAFF_CERT_EXPIRED_AT_ASSIGNMENT` — this is the only place the
    today-dated check is applied."

    Design: Corner/validations/assignment_rungs_reject_a_missing_and_an_already_expired_certification
    """
    program = create_program(
        name="Adaptive Aquatics",
        activity_type="AQUATICS",
        required_certification_types=["CPR"],
    )
    session = create_session(program["id"])
    uncertified = create_staff(full_name="Uncertified Ali", role_title="Program Aide")["id"]
    lapsed = create_staff(full_name="Lapsed Lee", role_title="Program Aide")["id"]
    create_certification(
        lapsed, certification_type="CPR", issued_on="2024-04-30", expires_on="2026-04-30"
    )

    validate_error(
        api_client.create_staff_assignment(
            {"session_id": session["id"], "staff_member_id": uncertified,
             "assignment_role": "GROUP"},
            ADMIN,
        ),
        ApiErrorId.ERR_STAFF_CERT_MISSING.value,
        expected_status=422,
    )
    validate_error(
        api_client.create_staff_assignment(
            {"session_id": session["id"], "staff_member_id": lapsed,
             "assignment_role": "GROUP"},
            ADMIN,
        ),
        ApiErrorId.ERR_STAFF_CERT_EXPIRED_AT_ASSIGNMENT.value,
        expected_status=422,
    )

    assert read_session(session["id"])["assigned_group_staff_count"] == 0
    _rows, meta = validate_paginated(
        api_client.list_staff_assignments(ADMIN, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0


def test_staffing_gap_blocks_the_lock():
    """PRD §3.5: "Locking staffing takes an `OPEN` session to `STAFFING_LOCKED`
    and demands four things: the recomputed `staffing_gap` must be 0, or the lock
    fails with `ERR_STAFFING_GAP`"
    PRD §2.10 rung 47: "On staffing lock, the session's recomputed `staffing_gap`
    is 0 — otherwise `ERR_STAFFING_GAP` (409)."

    Design: Corner/validations/staffing_gap_blocks_the_lock
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant()
    create_confirmed_enrollment(who["participant"]["id"], session["id"])
    staff_id = create_staff()["id"]

    validate_error(
        api_client.lock_staffing(session["id"], make_activity_lead_headers(staff_id)),
        ApiErrorId.ERR_STAFFING_GAP.value,
        expected_status=409,
    )

    after = read_session(session["id"])
    assert after["status"] == "OPEN"
    assert after["staffing_gap"] == 1
    assert after["required_group_staff_planned"] == 1
    assert after["assigned_group_staff_count"] == 0


def test_medication_admin_coverage_missing_blocks_the_lock():
    """PRD §3.5: "and when the programme's `requires_medication_admin` is true, at
    least one live assignment on the session must be held by a staffer with a
    `MEDICATION_ADMIN` certification whose `expires_on` is on or after the
    session date, failing which the lock reports
    `ERR_MED_ADMIN_COVERAGE_MISSING`."
    PRD §2.10 rung 38: "On staffing lock, when the programme's
    `requires_medication_admin` is true, the session carries at least one live
    assignment (status `PROPOSED` or `CONFIRMED`) whose staff member holds a
    `MEDICATION_ADMIN` certification whose `expires_on` is on or after the
    session date — otherwise `ERR_MED_ADMIN_COVERAGE_MISSING` (422)."

    Design: Corner/validations/medication_admin_coverage_missing_blocks_the_lock
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Med-Support Outing",
            "activity_type": "COMMUNITY_OUTING",
            "requires_medication_admin": True,
        }
    )
    who = create_active_participant()
    create_confirmed_enrollment(who["participant"]["id"], session["id"])
    staff_id = create_staff()["id"]
    create_certification(
        staff_id, certification_type="CPR", issued_on="2025-06-01", expires_on="2027-06-01"
    )
    assignment = propose_assignment(session["id"], staff_id)

    assert read_session(session["id"])["staffing_gap"] == 0, (
        "the gap is closed, so the failure cannot be ERR_STAFFING_GAP"
    )

    validate_error(
        api_client.lock_staffing(session["id"], make_activity_lead_headers(staff_id)),
        ApiErrorId.ERR_MED_ADMIN_COVERAGE_MISSING.value,
        expected_status=422,
    )

    assert read_session(session["id"])["status"] == "OPEN"
    assert read_assignment(assignment["id"])["status"] == "PROPOSED"


def test_certification_lapse_unlocks_the_session_and_revalidate_restores_the_assignment():
    """PRD §3.5: "Hop 2, caused by hop 1, takes every assignment held by that
    staffer whose `status` is `CONFIRMED`, sitting on a session whose `status` is
    `OPEN` or `STAFFING_LOCKED` and whose programme's
    `required_certification_types` includes the expiring type, and moves it from
    `CONFIRMED` to `LAPSED`, setting that assignment's
    `qualified_at_session_date` to false."
    PRD §3.5: "Hop 4, caused by hop 3, takes every affected session whose
    `status` is `STAFFING_LOCKED` and whose recomputed `staffing_gap` is now
    above 0 and moves it from `STAFFING_LOCKED` back to `OPEN`, raising its
    `unlock_count` by one"
    PRD §3.5: "**A renewal never revives a lapsed assignment on its own** — the
    assignment must be revalidated explicitly."

    Design: Corner/state_machines/certification_lapse_unlocks_the_session_and_revalidate_restores_the_assignment
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Aquatics",
            "activity_type": "AQUATICS",
            "required_certification_types": ["CPR"],
        }
    )
    staff_id = create_staff()["id"]
    certification = create_certification(
        staff_id, certification_type="CPR", issued_on="2024-06-15", expires_on="2026-06-15"
    )
    who = create_active_participant()
    create_confirmed_enrollment(who["participant"]["id"], session["id"])
    assignment = propose_assignment(session["id"], staff_id)
    confirm_assignment(assignment["id"], staff_id)
    lock_staffing(session["id"], staff_id)

    sweep = set_clock("2026-06-20T00:00:00Z")
    assert sweep["certifications_expired"] == 1
    assert sweep["assignments_lapsed"] == 1
    assert sweep["sessions_unlocked"] == 1

    assert validate_success(
        api_client.get_staff_certification(certification["id"], ADMIN)
    )["status"] == "EXPIRED"
    assert read_assignment(assignment["id"])["status"] == "LAPSED"
    after_sweep = read_session(session["id"])
    assert after_sweep["status"] == "OPEN"
    assert after_sweep["unlock_count"] == 1

    renewed = validate_success(
        api_client.renew_certification(
            certification["id"], {"new_expires_on": "2027-06-30"}, ADMIN
        )
    )
    assert renewed["status"] == "VALID"
    assert read_assignment(assignment["id"])["status"] == "LAPSED", (
        "a renewal alone must not revive the lapsed assignment"
    )

    restored = validate_success(
        api_client.revalidate_assignment(
            assignment["id"], make_activity_lead_headers(staff_id)
        )
    )
    assert restored["status"] == "CONFIRMED"
    assert restored["qualified_at_session_date"] is True
    assert read_session(session["id"])["staffing_gap"] == 0


def test_delivered_session_keeps_the_tier_it_was_staffed_under():
    """PRD §3.5: "Once the session's status is `DELIVERED`, the `AS_OF_SESSION`
    variant applies instead: gather the participant's assessments whose `status`
    is `ACTIVE` or `SUPERSEDED` and whose `effective_from` is at or before the
    session's `start_at`, rank them by `effective_from` descending with ties
    broken by `created_at` descending, and take the first one's `support_tier`,
    or null when that set is empty."
    PRD §3.5: "A delivered session consequently keeps the tier it was staffed
    under, even after the participant has been re-assessed — the two variants
    really do return different tiers on the same underlying data."

    Design: Corner/calculations/delivered_session_keeps_the_tier_it_was_staffed_under_after_a_reassessment
    """
    create_fee_band()
    _program, session = create_open_session()
    who = create_active_participant(support_tier="SUBSTANTIAL")
    participant_id = who["participant"]["id"]
    enrollment = create_confirmed_enrollment(participant_id, session["id"])
    staff_id = create_staff()["id"]
    propose_assignment(session["id"], staff_id)
    lock_staffing(session["id"], staff_id)
    set_clock("2026-06-10T15:00:00Z")
    record_attendance(enrollment["id"], staff_id, "ATTENDED")
    set_clock("2026-06-10T16:30:00Z")
    deliver_session(session["id"], staff_id)

    later = create_assessment(
        participant_id,
        assessed_on="2026-06-20",
        effective_from="2026-07-01T00:00:00Z",
        support_tier="INDEPENDENT",
    )
    activate_assessment(later["id"])

    assert read_participant(participant_id)["effective_support_tier"] == "INDEPENDENT"
    assert read_enrollment(enrollment["id"])["effective_support_tier_at_session"] == "SUBSTANTIAL"
    assert staffing_summary(session["id"])["required_group_staff_delivered"] == 1
