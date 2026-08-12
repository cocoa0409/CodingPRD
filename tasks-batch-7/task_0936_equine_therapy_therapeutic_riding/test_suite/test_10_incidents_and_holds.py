"""Safety incidents, the hold cascade and the return to service."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assign_crew,
    book_session,
    complete_session,
    confirm_session,
    file_incident,
    file_release,
    make_leader,
    make_sidewalker,
    read_crew_assignment,
    read_horse,
    read_incident,
    read_instructor,
    read_rider,
    read_session,
    read_volunteer,
    set_clock,
    setup_active_rider,
    setup_level_3_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK


def _sev_1_cascade_scenario():
    """Two crewed sessions; the earlier one is completed and then carries a SEV_1 fall."""
    scenario = setup_level_3_rider()
    leader = make_leader()
    sidewalker = make_sidewalker()

    sessions = {}
    for key, start in (("past", "2026-05-11T10:00:00Z"), ("future", "2026-05-12T10:00:00Z")):
        session = book_session(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start=start,
            duration_minutes=60,
        )
        leader_assignment = assign_crew(session["id"], leader["volunteer_id"], "LEADER")
        sidewalker_assignment = assign_crew(
            session["id"],
            sidewalker["volunteer_id"],
            "SIDEWALKER",
            hold_type="ARM_OVER_THIGH",
        )
        confirm_session(session["id"], scenario["instructor_id"])
        sessions[key] = {
            "session": session,
            "leader_assignment": leader_assignment,
            "sidewalker_assignment": sidewalker_assignment,
        }

    set_clock("2026-05-11T11:30:00Z")
    complete_session(sessions["past"]["session"]["id"], scenario["instructor_id"], 60)

    incident = file_incident(
        sessions["past"]["session"]["id"],
        scenario["instructor_id"],
        incident_type="FALL",
        injury_reported=True,
        occurred_at="2026-05-11T10:30:00Z",
        narrative="Rider dismounted unexpectedly and reported pain",
    )
    scenario.update(
        {
            "leader": leader,
            "sidewalker": sidewalker,
            "sessions": sessions,
            "incident": incident,
        }
    )
    return scenario


def test_incident_cascade_places_the_rider_hold_and_cancels_the_future_session(api):
    """PRD 3.9: "A rider hold moves the rider `ACTIVE → MEDICAL_HOLD` and sets
    `medical_hold_incident_id` to the new incident's `id`. A horse hold moves the
    horse `AVAILABLE → REST_HOLD` with `hold_reason` the literal
    `INCIDENT_REST_HOLD` and `hold_release_at` three days after the incident's
    `occurred_at`."
    PRD 3.9: "Hop two, caused by hop one, cancels every session of that rider
    whose `schedule_status` is `CREW_PENDING` or `CONFIRMED` and whose
    `scheduled_start` is still in the future relative to the logical clock,
    storing `RIDER_HOLD` as each session's `cancellation_reason`; **no fee is
    created for any of them, whatever the notice window would otherwise have
    implied**, and the incident's `cancelled_session_count` records how many were
    cancelled."

    Design: Difficulty/transitive_cascade/incident_hold_four_hop_cascade_releases_future_crew
    """
    scenario = _sev_1_cascade_scenario()
    incident = scenario["incident"]

    assert incident["severity"] == "SEV_1"
    assert incident["status"] == "OPEN"
    assert incident["reported_late"] is False
    assert incident["cancelled_session_count"] == 1

    rider = read_rider(scenario["rider_id"])
    assert rider["status"] == "MEDICAL_HOLD"
    assert rider["medical_hold_incident_id"] == incident["id"]

    future = read_session(scenario["sessions"]["future"]["session"]["id"])
    assert future["schedule_status"] == "CANCELLED"
    assert future["cancellation_reason"] == "RIDER_HOLD"
    assert future["billing_status"] == "UNBILLED"
    _, charge_meta = validate_paginated(
        api.list_charges(CLERK, params={"session_id": future["id"]})
    )
    assert charge_meta["total_count"] == 0

    past = read_session(scenario["sessions"]["past"]["session"]["id"])
    assert past["schedule_status"] == "COMPLETED", (
        "A past session is never swept by the hold"
    )

    horse = read_horse(scenario["horse_id"])
    assert horse["status"] == "REST_HOLD"
    assert horse["hold_reason"] == "INCIDENT_REST_HOLD"
    assert_same_instant(horse["hold_release_at"], "2026-05-14T10:30:00.000Z")


def test_incident_cascade_releases_crew_and_drops_open_assignment_counts(api):
    """PRD 3.9: "Hop three, caused by hop two, releases every `ASSIGNED` crew
    assignment on each of those cancelled sessions, writing `SESSION_CANCELLED`
    as each `release_reason`. Hop four, caused by hop three, re-derives every
    affected volunteer's `open_assignment_count` downward."

    Design: Difficulty/transitive_cascade/incident_hold_four_hop_cascade_releases_future_crew
    """
    scenario = _sev_1_cascade_scenario()
    future = scenario["sessions"]["future"]

    leader_assignment = read_crew_assignment(future["leader_assignment"]["id"])
    sidewalker_assignment = read_crew_assignment(future["sidewalker_assignment"]["id"])
    assert leader_assignment["status"] == "RELEASED"
    assert sidewalker_assignment["status"] == "RELEASED"
    assert leader_assignment["release_reason"] == "SESSION_CANCELLED"
    assert sidewalker_assignment["release_reason"] == "SESSION_CANCELLED"

    assert read_volunteer(scenario["leader"]["volunteer_id"])["open_assignment_count"] == 0
    assert (
        read_volunteer(scenario["sidewalker"]["volunteer_id"])["open_assignment_count"]
        == 0
    )


def test_late_report_is_recorded_not_rejected(api):
    """PRD 3.9: "`report_due_at` is 24 hours after `occurred_at` for a `SEV_1`,
    48 hours for a `SEV_2` and 72 hours for a `SEV_3`, and `reported_late` is
    true when `reported_at` is strictly after `report_due_at` — reporting exactly
    at the deadline is on time. A late report is **recorded and never rejected**:
    the centre would rather have a late incident report than none."
    PRD 3.9: "A `NEAR_MISS` is `SEV_3` either way."
    PRD 3.9: "For a `SEV_3` all four are false and no hold of any kind is
    placed."

    Design: Corner/calculations/incident_reported_after_its_deadline_is_recorded_late_not_rejected
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    set_clock("2026-05-11T11:30:00Z")
    complete_session(session["id"], scenario["instructor_id"], 60)

    set_clock("2026-05-14T12:00:00Z")
    response = api.create_incident(
        session["id"],
        {
            "incident_type": "NEAR_MISS",
            "injury_reported": False,
            "occurred_at": "2026-05-11T10:00:00Z",
            "narrative": "Horse spooked at a bird, rider stayed on",
        },
        scenario["instructor_headers"],
    )
    incident = validate_success(response, expected_status=201)

    assert incident["severity"] == "SEV_3"
    assert incident["reported_late"] is True
    assert_same_instant(incident["report_due_at"], "2026-05-14T10:00:00.000Z")
    assert_same_instant(incident["reported_at"], "2026-05-14T12:00:00.000Z")
    assert incident["rider_hold_applied"] is False
    assert incident["horse_hold_applied"] is False
    assert incident["volunteer_suspension_applied"] is False
    assert incident["instructor_suspension_applied"] is False
    assert incident["cancelled_session_count"] == 0

    assert read_rider(scenario["rider_id"])["status"] == "ACTIVE"
    assert read_horse(scenario["horse_id"])["status"] == "AVAILABLE"


def test_closing_an_open_incident_is_refused(api):
    """PRD 3.9: "A `ProgramAdmin` supplies a `resolution` together with three
    booleans — `release_rider_hold`, `release_horse_hold` and
    `release_volunteer_suspension` — and the incident moves `UNDER_REVIEW →
    CLOSED`; closing an incident still in `OPEN` is `ERR_INVALID_STATE`."
    PRD 3.9: "For a `SEV_2`, `horse_hold_applied` is true and
    `volunteer_suspension_applied` is true when a volunteer was implicated, while
    `rider_hold_applied` and `instructor_suspension_applied` are false."

    Design: Corner/state_machines/close_incident_from_open_returns_invalid_state
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    set_clock("2026-05-11T11:30:00Z")
    complete_session(session["id"], scenario["instructor_id"], 60)

    incident = file_incident(
        session["id"],
        scenario["instructor_id"],
        incident_type="FALL",
        injury_reported=False,
        occurred_at="2026-05-11T10:30:00Z",
        narrative="Unplanned dismount, no injury",
    )
    assert incident["severity"] == "SEV_2"

    refused = api.close_incident(
        incident["id"],
        {
            "resolution": "No action",
            "release_rider_hold": False,
            "release_horse_hold": True,
            "release_volunteer_suspension": False,
        },
        ADMIN,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = read_incident(incident["id"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["resolution"] is None

    assert read_rider(scenario["rider_id"])["status"] == "ACTIVE", (
        "A SEV_2 places no rider medical hold"
    )
    horse = read_horse(scenario["horse_id"])
    assert horse["status"] == "REST_HOLD"
    assert_same_instant(horse["hold_release_at"], "2026-05-14T10:30:00.000Z")


def test_medical_clearance_only_after_the_hold_is_released(api):
    """PRD 3.9: "When `release_rider_hold` is true, the rider's
    `medical_hold_incident_id` is cleared — but the rider **stays** in
    `MEDICAL_HOLD`. Closing the incident alone never returns a rider to riding; a
    fresh physician clearance is always required, and only then may a
    `ProgramAdmin` move the rider `MEDICAL_HOLD → ACTIVE` by naming a
    `medical_release_id` belonging to that rider whose derived status is
    `ACTIVE`, together with a `note`."
    PRD 3.1: "a `ProgramAdmin` grants medical clearance by naming a
    `medical_release_id` together with a `note`, and the rider moves
    `MEDICAL_HOLD → ACTIVE` only when `medical_hold_incident_id` has already been
    cleared and the named release belongs to this rider and is `ACTIVE`."
    PRD 3.9: "The suspended instructor is released unconditionally on close — no
    flag governs it — with `suspended_until` set back to null."

    Design: Corner/state_machines/medical_clearance_returns_a_held_rider_to_active_only_after_the_hold_is_released
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    set_clock("2026-05-11T11:30:00Z")
    complete_session(session["id"], scenario["instructor_id"], 60)

    incident = file_incident(
        session["id"],
        scenario["instructor_id"],
        incident_type="MEDICAL_EVENT",
        injury_reported=False,
        occurred_at="2026-05-11T10:20:00Z",
        narrative="Seizure activity observed",
    )
    assert incident["severity"] == "SEV_1"

    fresh_release = file_release(
        scenario["rider_id"], signed_on="2026-05-11", physician_name="Dr Elm"
    )

    too_early = api.grant_medical_clearance(
        scenario["rider_id"],
        {"medical_release_id": fresh_release["id"], "note": "Cleared by neurologist"},
        ADMIN,
    )
    validate_error(too_early, ApiErrorId.ERR_INVALID_STATE.value)

    validate_success(
        api.review_incident(
            incident["id"], {"reviewer_notes": "Reviewed with medical director"}, ADMIN
        )
    )
    validate_success(
        api.close_incident(
            incident["id"],
            {
                "resolution": "Cleared to ride",
                "release_rider_hold": True,
                "release_horse_hold": True,
                "release_volunteer_suspension": False,
            },
            ADMIN,
        )
    )

    after_close = read_rider(scenario["rider_id"])
    assert after_close["status"] == "MEDICAL_HOLD"
    assert after_close["medical_hold_incident_id"] is None

    cleared = validate_success(
        api.grant_medical_clearance(
            scenario["rider_id"],
            {
                "medical_release_id": fresh_release["id"],
                "note": "Cleared by neurologist",
            },
            ADMIN,
        )
    )
    assert cleared["status"] == "ACTIVE"

    assert read_horse(scenario["horse_id"])["status"] == "AVAILABLE"
    assert (
        read_instructor(scenario["instructor_id"])["certification_status"] == "CURRENT"
    )

    closed = read_incident(incident["id"])
    assert closed["status"] == "CLOSED"
    assert_same_instant(closed["report_due_at"], "2026-05-12T10:20:00.000Z")
    assert closed["reported_late"] is False
