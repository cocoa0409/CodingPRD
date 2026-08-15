"""Trip lifecycle: initial state, illegal transitions, terminal lockdown, and
the full happy path through debrief to program close."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_program,
    create_trip,
    get_account_for_registration,
    get_registration,
    make_director_headers,
    set_clock,
    setup_in_progress_trip_with_confirmed,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()

DEBRIEF_PAYLOAD = {
    "debrief_summary": "25 hours of service completed",
    "debrief_actual_participant_count": 1,
    "debrief_incident_count": 0,
    "debrief_lessons_learned": "book rooms earlier",
}


class TestTripInitialAndInvalidTransitions:
    def test_trip_initial_state_and_invalid_from_transitions(self, api):
        """PRD §3.2: "A new trip is `DRAFT` with all rollups zeroed."
        PRD §3.2: opening registration requires "the trip must be `DRAFT`
        (otherwise `ERR_TRIP_STATE_FORBIDS_ACTION`)"; closing registration moves
        "`REGISTRATION_OPEN` to `REGISTRATION_CLOSED`"; locking requires
        "`REGISTRATION_CLOSED` (`ERR_TRIP_STATE_FORBIDS_ACTION`)"; starting and
        debrief require `ROSTER_LOCKED` and `IN_PROGRESS` respectively.

        Design: Corner/state_machines/trip_initial_state_and_invalid_from_transitions
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")
        assert trip["status"] == "DRAFT"
        assert trip["seats_taken"] == 0
        assert trip["confirmed_youth_count"] == 0
        assert trip["lodging_cost_total_cents"] == 0

        for trigger in (
                lambda: api.start_trip(trip["id"], DIRECTOR),
                lambda: api.lock_roster(trip["id"], DIRECTOR),
                lambda: api.close_registration(trip["id"], DIRECTOR),
                lambda: api.debrief_trip(trip["id"], DEBRIEF_PAYLOAD,
                                         DIRECTOR)):
            validate_error(trigger(),
                           ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION, 409)


class TestTripTerminalLockdown:
    def test_trip_terminal_states_locked(self, api):
        """PRD §3.2: "From `DRAFT`, cancel is quiet: no registrations can exist
        before registration opens, so there is no cascade at all — only the
        trip's own `version` advances." Once `CANCELLED` the trip is terminal:
        the enumerated cancel branches cover only `DRAFT`, `REGISTRATION_OPEN`,
        `REGISTRATION_CLOSED`, `ROSTER_LOCKED`, and `IN_PROGRESS`, and every
        other transition names its required from-state
        (`ERR_TRIP_STATE_FORBIDS_ACTION`).

        Design: Corner/state_machines/trip_terminal_states_locked
        """
        program = create_program(scholarship_fund_total_cents=500000)
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")
        cancelled = api.cancel_trip(trip["id"], DIRECTOR,
                                    payload={"reason": "scouting failed"})
        data = validate_success(cancelled, 200)
        assert data["status"] == "CANCELLED"

        e_open = api.open_registration(trip["id"], DIRECTOR)
        validate_error(e_open, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION, 409)
        e_recancel = api.cancel_trip(trip["id"], DIRECTOR)
        validate_error(e_recancel, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION,
                       409)

        program_after = api.get_program(program["id"], DIRECTOR).json()["data"]
        assert program_after["scholarship_available_cents"] == 500000
        assert program_after["scholarship_reserved_cents"] == 0
        assert program_after["scholarship_disbursed_cents"] == 0


class TestDebriefLifecycle:
    def test_debrief_completes_roster_and_unlocks_program_close(self, api):
        """PRD §3.2: "Debrief (`IN_PROGRESS` to `DEBRIEFED`) is allowed only once
        the clock has reached midnight UTC on the day after `end_date`. Debrief
        records the post-trip report ... stamps `debriefed_at` from the clock (it
        is empty until then), and cascades: every `CONFIRMED` registration
        auto-transitions to `COMPLETED`, and every still-`OPEN` fundraising
        account belonging to those completed registrations closes."
        PRD §3.1: "closing requires the program to be `OPEN` and every one of its
        trips to have reached `DEBRIEFED` or `CANCELLED`; otherwise the close is
        rejected with `ERR_PROGRAM_HAS_OPEN_TRIPS` (HTTP 409)."

        Design: Corner/state_machines/debrief_completes_roster_and_unlocks_program_close
        """
        bundle = setup_in_progress_trip_with_confirmed(num_confirmed=1)
        program = bundle["program"]
        trip = bundle["trip"]
        registration = bundle["bundles"][0]["registration"]
        assert trip["status"] == "IN_PROGRESS"

        # Too early: the day after end_date (2027-06-16) is 2027-06-17.
        e_early = api.debrief_trip(trip["id"], DEBRIEF_PAYLOAD, DIRECTOR)
        validate_error(e_early, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION, 409)

        # Program cannot close while the trip is still IN_PROGRESS.
        e_close = api.close_program(program["id"], DIRECTOR)
        validate_error(e_close, ApiErrorId.ERR_PROGRAM_HAS_OPEN_TRIPS, 409)

        set_clock("2027-06-17T00:00:00Z")
        resp = api.debrief_trip(trip["id"], DEBRIEF_PAYLOAD, DIRECTOR)
        data = validate_success(resp, 200)
        assert data["status"] == "DEBRIEFED"
        assert data["debrief_summary"] == DEBRIEF_PAYLOAD["debrief_summary"]
        assert data["debrief_actual_participant_count"] == 1
        assert data["debrief_incident_count"] == 0
        assert data["debrief_lessons_learned"] == \
            DEBRIEF_PAYLOAD["debrief_lessons_learned"]
        assert_same_instant(data["debriefed_at"], "2027-06-17T00:00:00Z",
                            "debriefed_at")

        registration_after = get_registration(registration["id"])
        assert registration_after["registration_status"] == "COMPLETED"
        account = get_account_for_registration(registration["id"])
        assert account["status"] == "CLOSED"

        closed = api.close_program(program["id"], DIRECTOR)
        assert validate_success(closed, 200)["status"] == "CLOSED"
