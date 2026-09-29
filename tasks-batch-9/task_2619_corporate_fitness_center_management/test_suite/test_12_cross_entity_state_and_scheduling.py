"""Cross-entity state dependencies and the two scheduling interval geometries.

Two themes live in this module.

The first is that a transition on one entity can be legal or illegal purely
because of the live state of a *different* entity: a session start turns on its
room's posture, and a badge grant turns on the member's liability waiver.  Both
dependencies are re-read at the moment of the call, so the identical request
flips outcome when the related entity moves and flips back when it moves again.

The second is that this API deliberately carries two different interval
geometries.  A room is occupied as a closed interval expanded by a 15-minute
turnover buffer on the end side, so a session that merely touches an existing
booking's end instant is refused.  A person is occupied over a half-open
interval with no buffer at all, so the identical touching pair is permitted.
Each boundary is pinned from both sides — the rejected instant and the accepted
instant.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import THRESHOLDS, api_client, factories
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId

# The baseline lunchtime booking every scheduling scenario below is built around.
BASE_START_UTC = "2026-08-05T12:00:00Z"
BASE_END_UTC = "2026-08-05T12:55:00Z"
# Ten minutes before the baseline start, i.e. inside the start grace window.
GRACE_WINDOW_INSTANT = "2026-08-05T11:50:00Z"


# ==========================================================================
# Private composite setups
# ==========================================================================
def _setup_staffed_lunch_session():
    """ACTIVE cost-plus site, Studio A OPEN, one READY defibrillator, and a
    STAFFED session on 2026-08-05 12:00-12:55Z.  The clock is left at its
    startup instant, more than the 24-hour lock window before the session, so a
    room restriction cannot cascade into a cancellation."""
    scenario = scenarios.setup_active_program()
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=BASE_START_UTC,
        scheduled_end_utc=BASE_END_UTC,
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    scenarios.staff_session(scenario, session["id"])
    return scenario, scenarios.read_session(session["id"])


def _record_failing_inspection(scenario, room_id, inspection_on="2026-08-01"):
    """A cleanliness score of 78 with one deficiency: below the pass score and
    carrying a deficiency, so the inspection fails on both counts."""
    return validate_success(
        api_client.create_room_inspection(
            room_id,
            factories.inspection_payload(
                inspection_on=inspection_on,
                cleanliness_score=78,
                deficiency_count=1,
                notes="Sanitizer stations empty",
            ),
            scenario["manager_headers"],
        )
    )


def _record_passing_inspection(scenario, room_id, inspection_on="2026-08-05"):
    """A cleanliness score of 90 with zero deficiencies: a clean pass."""
    return validate_success(
        api_client.create_room_inspection(
            room_id,
            factories.inspection_payload(
                inspection_on=inspection_on,
                cleanliness_score=90,
                deficiency_count=0,
                notes="Re-stocked and cleared",
            ),
            scenario["manager_headers"],
        )
    )


def _start_session_response(scenario, session_id):
    return api_client.session_status_change(
        session_id, {"action": "START"}, scenario["manager_headers"]
    )


def _setup_verified_member_without_waiver():
    """ACTIVE cost-plus contract with a credentialed site manager, plus one
    EMPLOYEE member whose eligibility is verified and who holds no waiver row of
    any kind."""
    scenario = scenarios.setup_active_contract()
    member = scenarios.enrol_member(
        scenario, full_name="Ada Kim", employee_number="E-1001"
    )
    scenarios.verify_member(scenario, member["id"])
    return scenario, scenarios.read_member(member["id"])


def _grant_badge_response(scenario, member_id, badge_number="B-1001"):
    return api_client.badge_access(
        member_id,
        {"action": "GRANT", "badge_number": badge_number},
        scenario["manager_headers"],
    )


def _schedule_session_response(scenario, room_id, start_utc, end_utc):
    """Every candidate booking is identical to the baseline except its times."""
    return api_client.create_program_session(
        factories.program_session_payload(
            scenario["offering_id"],
            room_id,
            scheduled_start_utc=start_utc,
            scheduled_end_utc=end_utc,
            forecast_attendance=3,
            direct_supply_cost_cents=0,
        ),
        scenario["manager_headers"],
    )


def _assign_lead_response(scenario, session_id, staff_member_id):
    return api_client.create_staff_assignment(
        factories.staff_assignment_payload(
            session_id, staff_member_id, role_on_session="LEAD"
        ),
        scenario["manager_headers"],
    )


# ==========================================================================
# ProgramSession START depends on the live state of its FacilityRoom
# ==========================================================================
def test_failed_inspection_restricts_the_room_without_touching_its_staffed_session():
    """PRD §3.3: "An inspection **passes** when the `cleanliness_score` is at
    least 85 **and** the `deficiency_count` is exactly 0; anything else — a score
    below 85, or any deficiency at all, or both — **fails**."

    PRD §3.3: "A failing inspection on an `OPEN` room moves it `OPEN →
    RESTRICTED`, and the consequence reaches into the schedule."

    PRD §3.3: "Every inspection writes `last_inspection_on`,
    `last_cleanliness_score`, and `open_deficiency_count` onto the room from the
    supplied values; `open_deficiency_count` therefore tracks the deficiencies
    recorded by the *most recent* inspection that have not since been cleared by
    a passing one."

    PRD §3.3: "Sessions further out than the 24-hour lock window survive — there
    is still time to clean the room."

    Design: Difficulty/cross_entity_state_dependency/session_start_blocked_while_its_room_is_restricted
    """
    scenario, session = _setup_staffed_lunch_session()
    assert session["status"] == "STAFFED", (
        f"expected STAFFED, got {session['status']} after confirming the lead"
    )

    _record_failing_inspection(scenario, scenario["room_id"])

    room = scenarios.read_room(scenario["room_id"])
    assert room["room_state"] == "RESTRICTED", (
        f"expected RESTRICTED, got {room['room_state']} after an inspection "
        "scoring 78 with one deficiency"
    )
    assert room["open_deficiency_count"] == 1, (
        f"expected 1 open deficiency, got {room['open_deficiency_count']} "
        "from the failing inspection"
    )
    assert room["last_cleanliness_score"] == 78, (
        f"expected last_cleanliness_score 78, got {room['last_cleanliness_score']}"
    )

    after = scenarios.read_session(session["id"])
    assert after["status"] == "STAFFED", (
        f"expected the session to stay STAFFED, got {after['status']}: the "
        "inspection ran more than 24 hours before its start, so no facility "
        "cancellation cascade applies"
    )
    assert after["cancel_reason"] is None, (
        f"expected cancel_reason to stay null, got {after['cancel_reason']}"
    )
    assert after["started_at"] is None, (
        f"expected started_at to stay null, got {after['started_at']}"
    )


def test_session_start_refused_while_its_room_sits_restricted():
    """PRD §3.3: "While a room is `RESTRICTED` or `CLOSED` it hosts nothing at
    all: both scheduling a new session in it and starting a session already
    booked in it are refused with `ERR_ROOM_NOT_OPEN`."

    PRD §3.5: "**Starting** moves the session `STAFFED → IN_PROGRESS` and stamps
    `started_at`, and it is gated four ways: the session must be in `STAFFED`
    (else `ERR_SESSION_NOT_STAFFED`), the contract must be `ACTIVE` (else
    `ERR_CONTRACT_NOT_ACTIVE`), the room must be `OPEN` (else
    `ERR_ROOM_NOT_OPEN`), the site must have at least one `READY` defibrillator
    (else `ERR_AED_NOT_READY`), and the clock must have reached at most 15
    minutes before `scheduled_start_utc` — a start attempted earlier than that
    grace window is refused with `ERR_SESSION_START_TOO_EARLY`."

    Design: Difficulty/cross_entity_state_dependency/session_start_blocked_while_its_room_is_restricted
    """
    scenario, session = _setup_staffed_lunch_session()
    _record_failing_inspection(scenario, scenario["room_id"])

    # Ten minutes before the scheduled start, so the grace window is satisfied
    # and the only remaining obstacle is the room's posture.
    scenarios.set_clock(GRACE_WINDOW_INSTANT)

    response = _start_session_response(scenario, session["id"])
    validate_error(response, ApiErrorId.ERR_ROOM_NOT_OPEN.value)

    after = scenarios.read_session(session["id"])
    assert after["status"] == "STAFFED", (
        f"expected STAFFED, got {after['status']}: a refused START must not move "
        "the session"
    )
    assert after["started_at"] is None, (
        f"expected started_at to stay null, got {after['started_at']} after a "
        "refused START"
    )


def test_same_session_start_succeeds_once_a_passing_reinspection_reopens_the_room():
    """PRD §3.3: "A passing inspection on a `RESTRICTED` room moves it
    `RESTRICTED → OPEN`, resets `open_deficiency_count` to 0, and updates
    `last_cleanliness_score`; reopening a room additionally requires the owning
    contract to be `ACTIVE`, and an attempt while the contract sits elsewhere is
    refused with `ERR_CONTRACT_NOT_ACTIVE`."

    PRD §3.3: "While a room is `RESTRICTED` or `CLOSED` it hosts nothing at all:
    both scheduling a new session in it and starting a session already booked in
    it are refused with `ERR_ROOM_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/session_start_blocked_while_its_room_is_restricted
    """
    scenario, session = _setup_staffed_lunch_session()
    _record_failing_inspection(scenario, scenario["room_id"])
    scenarios.set_clock(GRACE_WINDOW_INSTANT)

    blocked = _start_session_response(scenario, session["id"])
    validate_error(blocked, ApiErrorId.ERR_ROOM_NOT_OPEN.value)

    _record_passing_inspection(scenario, scenario["room_id"])
    room = scenarios.read_room(scenario["room_id"])
    assert room["room_state"] == "OPEN", (
        f"expected OPEN, got {room['room_state']} after an inspection scoring 90 "
        "with zero deficiencies"
    )
    assert room["open_deficiency_count"] == 0, (
        f"expected the deficiency count reset to 0, got "
        f"{room['open_deficiency_count']} after the passing inspection"
    )

    # The identical START call, re-evaluated against the room's new posture.
    allowed = validate_success(_start_session_response(scenario, session["id"]))
    assert allowed["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS, got {allowed['status']} once the room reopened"
    )
    assert allowed["started_at"] == "2026-08-05T11:50:00.000Z", (
        f"expected started_at stamped from the logical clock instant "
        f"2026-08-05T11:50:00.000Z, got {allowed['started_at']}"
    )
    assert scenarios.read_session(session["id"])["status"] == "IN_PROGRESS", (
        "the persisted session must reflect the successful start"
    )


# ==========================================================================
# Member badge access depends on the live state of its LiabilityWaiver
# ==========================================================================
def test_badge_grant_refused_before_a_waiver_exists_and_accepted_once_one_is_signed():
    """PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from `REVOKED`
    to `ACTIVE`, and is gated twice: the member's `eligibility_status` must be
    `ELIGIBLE`, failing which the request is refused with
    `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a liability waiver
    in `SIGNED` status whose `expires_on` falls at or after today, failing which
    the request is refused with `ERR_WAIVER_REQUIRED`."

    PRD §3.6: "On success the new waiver is written in `SIGNED` status with
    `signed_at` stamped from the logical clock, the member's previously `SIGNED`
    waiver — if there was one — moves to `SUPERSEDED`, and the member's
    `current_waiver_id` is repointed at the new waiver while the member's own
    `version` advances."

    Design: Difficulty/cross_entity_state_dependency/badge_grant_depends_on_live_signed_waiver
    """
    scenario, member = _setup_verified_member_without_waiver()
    assert member["eligibility_status"] == "ELIGIBLE", (
        f"expected ELIGIBLE, got {member['eligibility_status']} after verification"
    )

    refused = _grant_badge_response(scenario, member["id"])
    validate_error(refused, ApiErrorId.ERR_WAIVER_REQUIRED.value)
    assert scenarios.read_member(member["id"])["access_status"] == "NO_BADGE", (
        "a refused grant must leave the badge dimension at NO_BADGE"
    )

    waiver = scenarios.file_waiver(scenario, member["id"], expires_on="2026-08-10")
    assert waiver["status"] == "SIGNED", (
        f"expected SIGNED, got {waiver['status']} on a freshly filed waiver"
    )
    after_filing = scenarios.read_member(member["id"])
    assert after_filing["current_waiver_id"] == waiver["id"], (
        f"expected current_waiver_id repointed at {waiver['id']}, got "
        f"{after_filing['current_waiver_id']}"
    )

    # The identical GRANT payload, re-evaluated against the live waiver row.
    granted = validate_success(_grant_badge_response(scenario, member["id"]))
    assert granted["access_status"] == "ACTIVE", (
        f"expected ACTIVE, got {granted['access_status']} once a SIGNED waiver "
        "was on file"
    )


def test_waiver_expiry_in_the_ops_run_pulls_the_badge_back_without_touching_eligibility():
    """PRD §3.6: "Waivers reach `EXPIRED` only through the nightly sweep, which
    moves a `SIGNED` waiver to `EXPIRED` once its `expires_on` falls strictly
    before today, clears the member's `current_waiver_id` to null, and — when the
    member's `access_status` was `ACTIVE` — revokes the badge."

    PRD §3.9: "Every count is the number of records the run itself transitioned,
    not a standing total, so a second run over an unchanged contract returns
    zeros throughout."

    Design: Difficulty/cross_entity_state_dependency/badge_grant_depends_on_live_signed_waiver
    """
    scenario, member = _setup_verified_member_without_waiver()
    waiver = scenarios.file_waiver(scenario, member["id"], expires_on="2026-08-10")
    validate_success(_grant_badge_response(scenario, member["id"]))
    assert scenarios.read_member(member["id"])["access_status"] == "ACTIVE", (
        "the badge must be ACTIVE before the waiver is allowed to lapse"
    )

    # 2026-08-11 is strictly after the waiver's 2026-08-10 expiry date.
    scenarios.set_clock("2026-08-11T06:00:00Z")
    tally = scenarios.run_readiness_sweep(scenario["contract_id"])
    assert tally["waivers_expired"] == 1, (
        f"expected waivers_expired 1, got {tally['waivers_expired']} from the run "
        "that lapsed the only signed waiver"
    )
    assert tally["badges_revoked"] == 1, (
        f"expected badges_revoked 1, got {tally['badges_revoked']} from the "
        "waiver expiry pulling the badge"
    )

    assert scenarios.read_waiver(waiver["id"])["status"] == "EXPIRED", (
        "the waiver must be EXPIRED after the run"
    )
    after = scenarios.read_member(member["id"])
    assert after["access_status"] == "REVOKED", (
        f"expected REVOKED, got {after['access_status']}: the badge is pulled "
        "purely because the related waiver crossed into EXPIRED"
    )
    assert after["current_waiver_id"] is None, (
        f"expected current_waiver_id cleared to null, got "
        f"{after['current_waiver_id']}"
    )
    assert after["eligibility_status"] == "ELIGIBLE", (
        f"expected the eligibility dimension untouched at ELIGIBLE, got "
        f"{after['eligibility_status']}"
    )


def test_badge_grant_refused_again_after_the_waiver_expires():
    """PRD §3.6: "A **grant** takes the member from `NO_BADGE` or from `REVOKED`
    to `ACTIVE`, and is gated twice: the member's `eligibility_status` must be
    `ELIGIBLE`, failing which the request is refused with
    `ERR_ELIGIBILITY_NOT_VERIFIED`; and the member must hold a liability waiver
    in `SIGNED` status whose `expires_on` falls at or after today, failing which
    the request is refused with `ERR_WAIVER_REQUIRED`."

    PRD §3.6: "A grant leaves `eligibility_status` unchanged."

    Design: Difficulty/cross_entity_state_dependency/badge_grant_depends_on_live_signed_waiver
    """
    scenario, member = _setup_verified_member_without_waiver()
    scenarios.file_waiver(scenario, member["id"], expires_on="2026-08-10")
    validate_success(_grant_badge_response(scenario, member["id"]))

    scenarios.set_clock("2026-08-11T06:00:00Z")
    scenarios.run_readiness_sweep(scenario["contract_id"])

    # The grant that succeeded an instant ago is refused now: the gate reads the
    # waiver's live status rather than a decision cached at first grant.
    refused = _grant_badge_response(scenario, member["id"])
    validate_error(refused, ApiErrorId.ERR_WAIVER_REQUIRED.value)

    after = scenarios.read_member(member["id"])
    assert after["access_status"] == "REVOKED", (
        f"expected the badge to stay REVOKED, got {after['access_status']} after "
        "a refused re-grant"
    )
    assert after["eligibility_status"] == "ELIGIBLE", (
        f"expected eligibility unchanged at ELIGIBLE, got "
        f"{after['eligibility_status']}"
    )


# ==========================================================================
# FacilityRoom occupancy: a closed interval expanded by the turnover buffer
# ==========================================================================
def _setup_room_with_baseline_booking():
    """ACTIVE cost-plus site with Studio A OPEN and one baseline session holding
    the room from 12:00:00Z to 12:55:00Z on 2026-08-05."""
    scenario = scenarios.setup_active_program()
    baseline = scenarios.schedule_session(
        scenario,
        scheduled_start_utc=BASE_START_UTC,
        scheduled_end_utc=BASE_END_UTC,
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    return scenario, baseline


def test_room_rejects_a_session_starting_exactly_when_the_previous_one_ends():
    """PRD §3.5: "Rooms need turnover between bookings, so a session occupies its
    room as a **closed** interval from `scheduled_start_utc` to
    `scheduled_end_utc`, **expanded by 15 minutes on the end side only**."

    PRD §3.5: "Two consequences follow directly and must both hold in an
    implementation: two sessions that merely touch on their raw endpoints — the
    new one starting at exactly the instant the existing one ends — **do**
    conflict, because the room is still being cleaned; and a gap of exactly 15
    minutes between them — the new one starting at exactly the existing end plus
    15 minutes — does **not** conflict."

    PRD §3.5: "A new session lands in `SCHEDULED` with `actual_attendance` at 0,
    `cancel_reason`, `started_at`, and `completed_at` all null, and a computed
    `scheduled_minutes` equal to the whole number of minutes between its start
    and end instants."

    Design: Difficulty/resource_temporal_overlap/room_buffered_closed_interval_rejects_touching_session
    """
    scenario, baseline = _setup_room_with_baseline_booking()
    assert baseline["scheduled_minutes"] == 55, (
        f"expected 55 scheduled minutes between 12:00:00Z and 12:55:00Z, got "
        f"{baseline['scheduled_minutes']}"
    )

    touching = _schedule_session_response(
        scenario,
        scenario["room_id"],
        "2026-08-05T12:55:00Z",
        "2026-08-05T13:50:00Z",
    )
    validate_error(touching, ApiErrorId.ERR_ROOM_TIME_CONFLICT.value)

    items, meta = validate_paginated(
        api_client.list_program_sessions(
            scenario["admin_headers"], params={"room_id": scenario["room_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the baseline booking alone, got {meta['total_count']} sessions "
        "in the room after the rejected touching request"
    )
    assert [item["id"] for item in items] == [baseline["id"]], (
        "the rejected request must not have created a session"
    )


def test_room_rejects_a_session_starting_inside_the_turnover_buffer():
    """PRD §3.5: "The new session conflicts with an existing session of the same
    room whenever the new start falls earlier than the existing end plus 15
    minutes **and** the existing start falls earlier than the new end plus 15
    minutes; the comparison runs against every session of that room whose status
    is not one of the three cancelled statuses."

    PRD §3.5: "A conflict is refused with `ERR_ROOM_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_buffered_closed_interval_rejects_touching_session
    """
    scenario, baseline = _setup_room_with_baseline_booking()

    # 13:05:00Z is ten minutes into the fifteen-minute buffer that follows the
    # baseline's 12:55:00Z end, so the room is still occupied.
    inside_buffer = _schedule_session_response(
        scenario,
        scenario["room_id"],
        "2026-08-05T13:05:00Z",
        "2026-08-05T14:00:00Z",
    )
    validate_error(inside_buffer, ApiErrorId.ERR_ROOM_TIME_CONFLICT.value)

    _, meta = validate_paginated(
        api_client.list_program_sessions(
            scenario["admin_headers"], params={"room_id": scenario["room_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the baseline booking alone, got {meta['total_count']} sessions "
        "after a request rejected inside the turnover buffer"
    )


def test_room_accepts_a_session_starting_exactly_one_buffer_after_the_previous_end():
    """PRD §3.5: "Two consequences follow directly and must both hold in an
    implementation: two sessions that merely touch on their raw endpoints — the
    new one starting at exactly the instant the existing one ends — **do**
    conflict, because the room is still being cleaned; and a gap of exactly 15
    minutes between them — the new one starting at exactly the existing end plus
    15 minutes — does **not** conflict."

    PRD §3.5: "A conflict is refused with `ERR_ROOM_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_buffered_closed_interval_rejects_touching_session
    """
    scenario, baseline = _setup_room_with_baseline_booking()
    buffer_minutes = THRESHOLDS["ROOM_TURNOVER_BUFFER_MIN"]

    # All three candidates differ from the baseline only in their times.
    touching = _schedule_session_response(
        scenario, scenario["room_id"], "2026-08-05T12:55:00Z", "2026-08-05T13:50:00Z"
    )
    validate_error(touching, ApiErrorId.ERR_ROOM_TIME_CONFLICT.value)

    inside_buffer = _schedule_session_response(
        scenario, scenario["room_id"], "2026-08-05T13:05:00Z", "2026-08-05T14:00:00Z"
    )
    validate_error(inside_buffer, ApiErrorId.ERR_ROOM_TIME_CONFLICT.value)

    # 12:55:00Z plus the fifteen-minute buffer is exactly 13:10:00Z.
    cleared = validate_success(
        _schedule_session_response(
            scenario, scenario["room_id"], "2026-08-05T13:10:00Z", "2026-08-05T14:05:00Z"
        ),
        201,
    )
    assert cleared["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {cleared['status']} for a booking starting a "
        f"gap of exactly {buffer_minutes} minutes after the existing end"
    )

    items, meta = validate_paginated(
        api_client.list_program_sessions(
            scenario["admin_headers"], params={"room_id": scenario["room_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected exactly 2 sessions in the room — the baseline and the accepted "
        f"one — got {meta['total_count']}; the two rejected requests created "
        "nothing"
    )
    assert sorted(item["id"] for item in items) == sorted(
        [baseline["id"], cleared["id"]]
    ), "the room must hold exactly the baseline booking and the accepted booking"


# ==========================================================================
# StaffMember occupancy: a half-open interval with no buffer
# ==========================================================================
def _setup_staff_interval_scenario():
    """ACTIVE cost-plus site with four OPEN studios and one credentialed
    instructor.  Every candidate session below sits in a studio of its own, so
    the room rule can never be the reason for any outcome."""
    scenario = scenarios.setup_active_program()
    rooms = {"a": scenario["room_id"]}
    for key, room_name in (("b", "Studio B"), ("c", "Studio C"), ("d", "Studio D")):
        rooms[key] = scenarios.add_room(scenario, room_name=room_name)["id"]
    scenario["rooms"] = rooms
    return scenario


def _schedule_in_room(scenario, room_key, start_utc, end_utc):
    return scenarios.schedule_session(
        scenario,
        room_id=scenario["rooms"][room_key],
        scheduled_start_utc=start_utc,
        scheduled_end_utc=end_utc,
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )


def test_staff_may_take_a_back_to_back_assignment_the_room_rule_would_refuse():
    """PRD §3.5: "An assignment occupies the person over the **half-open**
    interval from the session's `scheduled_start_utc` up to but excluding its
    `scheduled_end_utc`, with **no buffer at all**."

    PRD §3.5: "Back-to-back sessions, where one ends at exactly the instant the
    next begins, are therefore perfectly legal for a person even though they
    would be illegal for a room; and the lead's setup allowance, though it is
    paid, is not part of the occupied interval."

    PRD §3.5: "`paid_minutes` is computed as the session's `scheduled_minutes`
    plus a setup allowance of 15 minutes when the `role_on_session` is `LEAD`,
    and simply the session's `scheduled_minutes` when it is `SUPPORT`."

    PRD §3.5: "The assignment starts in `ASSIGNED` with `confirmed_at` null and
    `labor_cost_cents` at 0 — labor cost stays 0 until the assignment actually
    reaches `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/staff_half_open_interval_allows_back_to_back_assignment
    """
    scenario = _setup_staff_interval_scenario()
    instructor_id = scenario["instructor_id"]
    session_x = _schedule_in_room(scenario, "a", BASE_START_UTC, BASE_END_UTC)
    session_y = _schedule_in_room(
        scenario, "b", "2026-08-05T12:55:00Z", "2026-08-05T13:50:00Z"
    )

    assignment_x = scenarios.assign_staff(
        scenario, session_x["id"], instructor_id, role_on_session="LEAD"
    )

    # The next session begins at exactly the instant the first one ends.
    assignment_y = validate_success(
        _assign_lead_response(scenario, session_y["id"], instructor_id), 201
    )
    assert assignment_y["status"] == "ASSIGNED", (
        f"expected ASSIGNED, got {assignment_y['status']} on a back-to-back "
        "assignment, which the half-open staff interval permits"
    )

    setup_allowance = THRESHOLDS["LEAD_SETUP_MIN"]
    for label, assignment in (("first", assignment_x), ("second", assignment_y)):
        paid = scenarios.read_assignment(assignment["id"])["paid_minutes"]
        assert paid == 70, (
            f"expected the {label} LEAD assignment to be paid 55 session minutes "
            f"plus the {setup_allowance}-minute setup allowance, got {paid}"
        )

    staff = scenarios.read_staff(instructor_id)
    assert staff["committed_minutes_current_period"] == 140, (
        "expected 140 committed minutes from two 70-minute LEAD assignments, got "
        f"{staff['committed_minutes_current_period']}: the paid setup allowance "
        "counts towards committed time even though it does not widen the "
        "occupied interval"
    )


def test_staff_assignment_refused_when_the_new_session_genuinely_overlaps():
    """PRD §3.5: "A new assignment conflicts with one of that person's existing
    assignments — those in `ASSIGNED`, `CONFIRMED`, or `VACANT_NEEDS_COVER`
    status — whenever the new start falls earlier than the existing end and the
    existing start falls earlier than the new end."

    PRD §3.5: "A conflict is refused with `ERR_STAFF_TIME_CONFLICT`."

    PRD §2.9: "A staff member's `committed_minutes_current_period` always equals
    the sum of `paid_minutes` across that person's assignments in `ASSIGNED`,
    `CONFIRMED`, or `COMPLETED` status."

    Design: Difficulty/resource_temporal_overlap/staff_half_open_interval_allows_back_to_back_assignment
    """
    scenario = _setup_staff_interval_scenario()
    instructor_id = scenario["instructor_id"]
    session_x = _schedule_in_room(scenario, "a", BASE_START_UTC, BASE_END_UTC)
    session_y = _schedule_in_room(
        scenario, "b", "2026-08-05T12:55:00Z", "2026-08-05T13:50:00Z"
    )
    # 12:30-13:25Z genuinely overlaps 12:00-12:55Z, in a studio of its own.
    session_z = _schedule_in_room(
        scenario, "c", "2026-08-05T12:30:00Z", "2026-08-05T13:25:00Z"
    )

    scenarios.assign_staff(
        scenario, session_x["id"], instructor_id, role_on_session="LEAD"
    )
    validate_success(_assign_lead_response(scenario, session_y["id"], instructor_id), 201)

    refused = _assign_lead_response(scenario, session_z["id"], instructor_id)
    validate_error(refused, ApiErrorId.ERR_STAFF_TIME_CONFLICT.value)

    staff = scenarios.read_staff(instructor_id)
    assert staff["committed_minutes_current_period"] == 140, (
        f"expected committed minutes to stay at 140, got "
        f"{staff['committed_minutes_current_period']}: the refused assignment "
        "committed nothing"
    )

    _, meta = validate_paginated(
        api_client.list_staff_assignments(
            scenario["admin_headers"], params={"staff_member_id": instructor_id}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected exactly 2 assignments for the instructor, got "
        f"{meta['total_count']} after the refused overlap"
    )
    assert scenarios.read_session(session_z["id"])["status"] == "SCHEDULED", (
        "the overlapping session must still exist as SCHEDULED — only the "
        "assignment was refused"
    )


def test_staff_interval_boundary_rejects_one_minute_of_overlap_but_allows_touching():
    """PRD §3.5: "An assignment occupies the person over the **half-open**
    interval from the session's `scheduled_start_utc` up to but excluding its
    `scheduled_end_utc`, with **no buffer at all**."

    PRD §3.5: "A new assignment conflicts with one of that person's existing
    assignments — those in `ASSIGNED`, `CONFIRMED`, or `VACANT_NEEDS_COVER`
    status — whenever the new start falls earlier than the existing end and the
    existing start falls earlier than the new end."

    PRD §3.5: "A conflict is refused with `ERR_STAFF_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/staff_half_open_interval_allows_back_to_back_assignment
    """
    scenario = _setup_staff_interval_scenario()
    instructor_id = scenario["instructor_id"]
    session_x = _schedule_in_room(scenario, "a", BASE_START_UTC, BASE_END_UTC)
    # One minute earlier than the existing end: a genuine, one-minute overlap.
    session_early = _schedule_in_room(
        scenario, "d", "2026-08-05T12:54:00Z", "2026-08-05T13:49:00Z"
    )
    # Exactly the existing end: the endpoint the half-open interval excludes.
    session_touching = _schedule_in_room(
        scenario, "b", "2026-08-05T12:55:00Z", "2026-08-05T13:50:00Z"
    )

    scenarios.assign_staff(
        scenario, session_x["id"], instructor_id, role_on_session="LEAD"
    )

    refused = _assign_lead_response(scenario, session_early["id"], instructor_id)
    validate_error(refused, ApiErrorId.ERR_STAFF_TIME_CONFLICT.value)

    accepted = validate_success(
        _assign_lead_response(scenario, session_touching["id"], instructor_id), 201
    )
    assert accepted["status"] == "ASSIGNED", (
        f"expected ASSIGNED, got {accepted['status']}: a start at exactly the "
        "existing end is outside the half-open occupied interval"
    )

    staff = scenarios.read_staff(instructor_id)
    assert staff["committed_minutes_current_period"] == 140, (
        f"expected 140 committed minutes from the two accepted LEAD assignments, "
        f"got {staff['committed_minutes_current_period']}"
    )
