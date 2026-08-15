"""Cleanup event lifecycle: postpone/reschedule loop, briefing guards, cancel,
no-show sweep, and the logical clock (PRD §2.5, §3.3)."""
from test_helpers import (
    ApiErrorId,
    brief_event,
    complete_event,
    create_adult_waiver,
    create_event,
    estimated_report_payload,
    get_event,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_waiver,
    setup_briefed_event,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestPostponeRescheduleCycle:
    def test_event_postpone_reschedule_cycle(self, api):
        """PRD §3.3: "Postponing moves the event to `POSTPONED`, increments
        `postpone_count`, and resets `briefing_attendee_count` to zero: a
        rescheduled event must be briefed again from scratch."
        PRD §3.3: "Supplying a new `scheduled_date` to a `POSTPONED` event is
        the reschedule path: the new date must again be at least 14 days past
        the clock date (`ERR_EVENT_TOO_SOON`) and must not collide with another
        live event's day-slot on the segment (`ERR_EVENT_WINDOW_OVERLAP`); on
        success the event returns to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/event_postpone_reschedule_cycle
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver(
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        brief_event(event["id"], group["id"], [waiver["id"]])

        p = validate_success(
            api.postpone_event(event["id"], {"reason": "storm warning"}, gl), 200)
        assert p["status"] == "POSTPONED"
        assert p["postpone_count"] == 1
        assert p["briefing_attendee_count"] == 0

        r = validate_success(
            api.edit_event(event["id"], {"scheduled_date": "2026-09-20"}, gl), 200)
        assert r["status"] == "SCHEDULED"
        assert r["scheduled_date"] == "2026-09-20"

        b = validate_success(
            api.record_briefing(
                event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl), 200)
        assert b["status"] == "BRIEFING_DONE"
        assert b["briefing_attendee_count"] == 1

        set_clock("2026-09-20T10:00:00Z")
        complete_event(event["id"], group["id"])
        f = get_event(event["id"])
        assert f["status"] == "COMPLETED"
        assert f["completed_weight_lbs"] == 25.5
        assert f["postpone_count"] == 1

    def test_postpone_invalidates_prior_briefing(self, api):
        """PRD §3.3: "Postponing moves the event to `POSTPONED`, increments
        `postpone_count`, and resets `briefing_attendee_count` to zero: a
        rescheduled event must be briefed again from scratch."

        Design: Difficulty/non_linear_state_machine/event_postpone_reschedule_cycle
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        brief_event(event["id"], group["id"], [waiver["id"]])
        p = validate_success(api.postpone_event(event["id"], {}, gl), 200)
        assert p["briefing_attendee_count"] == 0
        # Debris report is refused while the event is POSTPONED (not BRIEFING_DONE).
        set_clock("2026-09-10T10:00:00Z")
        resp = api.submit_debris_report(
            event["id"], estimated_report_payload(), gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BRIEFED)


class TestBriefingGuards:
    def test_briefing_after_cancel_returns_invalid_state(self, api):
        """PRD §3.3: "the event must be `SCHEDULED`, else
        `ERR_EVENT_NOT_SCHEDULED`"

        Design: Corner/state_machines/briefing_after_cancel_returns_invalid_state
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        validate_success(api.cancel_event(event["id"], {"reason": "low turnout"}, gl), 200)
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)

    def test_briefing_after_cancel_records_no_attendees(self, api):
        """PRD §3.3: "A recorded briefing moves the event to `BRIEFING_DONE`
        and sets `briefing_attendee_count` to the size of the attendee list."

        Design: Corner/state_machines/briefing_after_cancel_returns_invalid_state
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        validate_success(api.cancel_event(event["id"], {}, gl), 200)
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)
        after = get_event(event["id"])
        assert after["briefing_attendee_count"] == 0

    def test_double_briefing_rejected(self, api):
        """PRD §3.3: "the event must be `SCHEDULED`, else
        `ERR_EVENT_NOT_SCHEDULED`"

        Design: Corner/state_machines/double_briefing_rejected
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        brief_event(event["id"], group["id"], [waiver["id"]])
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)
        after = get_event(event["id"])
        assert after["briefing_attendee_count"] == 1

    def test_double_briefing_leaves_attendee_count_unchanged(self, api):
        """PRD §3.3: "A recorded briefing moves the event to `BRIEFING_DONE`
        and sets `briefing_attendee_count` to the size of the attendee list."

        Design: Corner/state_machines/double_briefing_rejected
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        w2 = create_adult_waiver(agreement["id"], group["id"], name="Ben Adult",
                                 dob="1988-03-15")
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        brief_event(event["id"], group["id"], [waiver["id"], w2["id"]])
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)
        after = get_event(event["id"])
        assert after["briefing_attendee_count"] == 2


class TestNoShowSweep:
    def test_unbriefed_past_event_swept_to_no_show(self, api):
        """PRD §3.3: "Events that simply never happen are caught by the clock:
        when an advance carries the clock date past the `scheduled_date` of an
        event still in `SCHEDULED` or `POSTPONED`, the no-show sweep moves it
        to `NO_SHOW` with the same reconcile-and-restock cascade."
        PRD §3.3: "terminal events again refuse with `ERR_EVENT_TERMINAL`."

        Design: Corner/state_machines/unbriefed_past_event_swept_to_no_show
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        set_clock("2026-09-11T09:00:00Z")
        ev = get_event(event["id"])
        assert ev["status"] == "NO_SHOW"
        resp = api.cancel_event(event["id"], {}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_TERMINAL)

    def test_no_show_is_terminal_for_postpone(self, api):
        """PRD §3.3: "an event in any terminal state — `COMPLETED`,
        `CANCELLED`, or `NO_SHOW` — refuses with `ERR_EVENT_TERMINAL`."

        Design: Corner/state_machines/unbriefed_past_event_swept_to_no_show
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        set_clock("2026-09-11T09:00:00Z")
        assert get_event(event["id"])["status"] == "NO_SHOW"
        resp = api.postpone_event(event["id"], {}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_TERMINAL)


class TestLogicalClock:
    def test_clock_rejects_backward_move(self, api):
        """PRD §2.5: "The clock must move strictly forward; a request that does
        not advance it is rejected."

        Design: Corner/validations/clock_rejects_backward_move
        """
        set_clock("2026-09-10T10:00:00Z")
        resp = api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        fwd = validate_success(
            api.set_clock({"to_iso8601": "2026-09-12T00:00:00Z"}, COORD), 200)
        assert fwd["current_utc"] == "2026-09-12T00:00:00Z"

    def test_clock_rejects_equal_move(self, api):
        """PRD §2.5: "The clock must move strictly forward; a request that does
        not advance it is rejected."

        Design: Corner/validations/clock_rejects_backward_move
        """
        set_clock("2026-09-10T10:00:00Z")
        resp = api.set_clock({"to_iso8601": "2026-09-10T10:00:00Z"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
