"""Event creation defaults, course permitting, and the posture gates that
guard DRAFT -> PERMITTED -> PUBLISHED -> LIVE."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_course_permit,
    assert_event,
    create_aid_station_payload,
    create_event,
    create_event_payload,
    create_permit_payload,
    create_road_segment_payload,
    create_volunteer_assignment_payload,
    create_wave_payload,
    get_success_data,
    make_race_director_headers,
    validate_error,
    validate_success,
)


class TestEventCreationDefaults:
    def test_creation_defaults_applied(self, api, race_director_headers):
        """PRD §3.1: "An event begins in `DRAFT` posture, created by a
        `RaceDirector` with a `name`, a `start_date` marking the scheduled
        first-wave start, a `has_swim` flag distinguishing triathlons from
        bike/run-only formats, a `water_pool_units` budget of total event
        water, and an optional `appeal_window_minutes` that defaults to 60
        minutes when omitted. At creation the event's `water_pool_remaining`
        equals `water_pool_units` and its `ops_run_index` checkpoint counter
        starts at 0."
        PRD §2.6: "At creation, an event whose `has_swim` flag is true starts
        at `PENDING_DECISION`".

        Design: Corner/entities/event_creation_defaults_applied
        """
        created = validate_success(api.create_event(
            create_event_payload(name="Tri A", has_swim=True, water_pool_units=800),
            race_director_headers), expected_status=201)
        assert_event(created)

        event = validate_success(api.get_event(created["id"], race_director_headers))
        assert event["posture"] == "DRAFT"
        assert event["swim_status"] == "PENDING_DECISION"
        assert event["water_pool_remaining"] == 800
        assert event["ops_run_index"] == 0
        assert event["version"] == 1
        assert event["appeal_window_minutes"] == 60, \
            "appeal_window_minutes defaults to 60 when omitted"

    def test_no_swim_event_sets_no_swim_status(self, api, race_director_headers):
        """PRD §2.6: "an event without a swim leg starts at `NO_SWIM`, which
        has no transitions."

        Design: Corner/entities/event_no_swim_sets_no_swim_status
        """
        created = validate_success(api.create_event(
            create_event_payload(name="Du B", has_swim=False, water_pool_units=100),
            race_director_headers), expected_status=201)
        event = validate_success(api.get_event(created["id"], race_director_headers))
        assert event["swim_status"] == "NO_SWIM", \
            "has_swim=false must yield NO_SWIM, never PENDING_DECISION"

    def test_get_event_not_found(self, api, race_director_headers):
        """PRD §2.9: "Endpoints that address nested resources validate path
        identifiers left to right — event first, then the child within that
        event, then any grandchild — and reject the request with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        correspond to an existing resource."

        Design: Corner/entities/event_get_not_found_returns_404
        """
        resp = api.get_event(NON_EXISTENT_UUID, race_director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_road_segment_end_before_start_returns_400(self, api):
        """PRD §3.1: "a planned closure window from `closure_start` to
        `closure_end`, where the end must be strictly later than the start."
        PRD §2.10: "then request-body validation: required fields, enum
        membership, field formats, datetime ordering where an end must be
        strictly later than its start, and the `reduced_seconds` range on
        appeal decisions, all under `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/road_segment_end_before_start_returns_400
        """
        from test_helpers import TEST_USERS
        event = create_event()
        resp = api.create_road_segment(
            event["id"],
            create_road_segment_payload(
                closure_start="2026-10-15T12:00:00Z",
                closure_end="2026-10-15T06:00:00Z"),
            TEST_USERS["permit_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestPermitting:
    def test_permit_approve_from_draft_rejected(self, api):
        """PRD §3.1: "A permit's lifecycle is cyclic. Submitting moves `DRAFT`
        to `SUBMITTED`". Approving a permit that was never submitted targets a
        resource not in a valid from-state.
        PRD §2.10: "then state-machine from-state validity
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/permit_approve_from_draft_returns_invalid_state
        """
        from test_helpers import (
            create_event, create_road_segment_payload, create_permit_payload,
        )
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        segment = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(), pc))
        permit = get_success_data(api.create_permit(
            segment["id"], create_permit_payload(), pc))
        assert permit["status"] == "DRAFT"

        resp = api.approve_permit(permit["id"], pc)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        after = validate_success(api.get_permit(permit["id"], pc))
        assert after["status"] == "DRAFT", "rejected approve must not change status"

    def test_permit_reject_resubmit_cycle(self, api):
        """PRD §3.1: "Submitting moves `DRAFT` to `SUBMITTED`; the same submit
        action resubmits a `REJECTED` permit, clearing its `rejection_reason`
        back to null, and this reject–resubmit loop may repeat without bound."

        Design: Difficulty/non_linear_state_machine/course_permit_reject_resubmit_cycle
        """
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        segment = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(), pc))
        permit = get_success_data(api.create_permit(
            segment["id"], create_permit_payload(), pc))
        get_success_data(api.submit_permit(permit["id"], pc))
        rejected = get_success_data(api.reject_permit(
            permit["id"], pc, reason="insufficient detour plan"))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "insufficient detour plan"

        resubmitted = validate_success(api.submit_permit(permit["id"], pc))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["rejection_reason"] is None, \
            "resubmission clears rejection_reason back to null"

        approved = validate_success(api.approve_permit(permit["id"], pc))
        assert_course_permit(approved)
        assert approved["status"] == "APPROVED", \
            "REJECTED -> SUBMITTED -> APPROVED cycle completed"

    def test_permit_reject_then_resubmit_records_reason_each_time(self, api):
        """PRD §3.1: "Rejection records the request body's `reason` onto
        `rejection_reason`." Combined with resubmission clearing it, a second
        rejection records the new reason.

        Design: Difficulty/non_linear_state_machine/course_permit_reject_resubmit_cycle
        """
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        segment = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(), pc))
        permit = get_success_data(api.create_permit(
            segment["id"], create_permit_payload(), pc))
        get_success_data(api.submit_permit(permit["id"], pc))
        get_success_data(api.reject_permit(permit["id"], pc, reason="first reason"))
        get_success_data(api.submit_permit(permit["id"], pc))
        rejected_again = get_success_data(
            api.reject_permit(permit["id"], pc, reason="second reason"))
        assert rejected_again["status"] == "REJECTED"
        assert rejected_again["rejection_reason"] == "second reason"

    def test_permit_buffered_window_conflict(self, api):
        """PRD §3.1: "within the same `road_segment_id`, no two `APPROVED`
        permits may sit within a 30-minute buffer of one another. A conflict
        exists when the candidate's `requested_start` falls strictly earlier
        than the other permit's `requested_end` plus 30 minutes and,
        symmetrically, the other permit's `requested_start` falls strictly
        earlier than the candidate's `requested_end` plus 30 minutes; touching
        at exactly 30 minutes of separation is allowed because both
        comparisons are strict. A conflicting approval is rejected with
        `ERR_PERMIT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/permit_buffered_window_conflict
        """
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        segment = get_success_data(api.create_road_segment(
            event["id"],
            create_road_segment_payload(closure_start="2026-10-15T06:00:00Z",
                                        closure_end="2026-10-15T16:00:00Z"),
            pc))
        p1 = get_success_data(api.create_permit(
            segment["id"],
            create_permit_payload(authority_name="City PD",
                                  requested_start="2026-10-15T06:00:00Z",
                                  requested_end="2026-10-15T10:00:00Z"),
            pc))
        get_success_data(api.submit_permit(p1["id"], pc))
        get_success_data(api.approve_permit(p1["id"], pc))

        # Gap of 20 minutes (< 30-minute buffer) -> conflict.
        p2 = get_success_data(api.create_permit(
            segment["id"],
            create_permit_payload(authority_name="County SO",
                                  requested_start="2026-10-15T10:20:00Z",
                                  requested_end="2026-10-15T14:00:00Z"),
            pc))
        get_success_data(api.submit_permit(p2["id"], pc))
        resp = api.approve_permit(p2["id"], pc)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value)

        # Gap of exactly 30 minutes (== buffer) -> allowed (strict inequality).
        p3 = get_success_data(api.create_permit(
            segment["id"],
            create_permit_payload(authority_name="State Patrol",
                                  requested_start="2026-10-15T10:30:00Z",
                                  requested_end="2026-10-15T14:00:00Z"),
            pc))
        get_success_data(api.submit_permit(p3["id"], pc))
        approved = validate_success(api.approve_permit(p3["id"], pc))
        assert approved["status"] == "APPROVED", \
            "exactly 30 minutes of separation is allowed"

    def test_permit_conflict_only_within_same_segment(self, api):
        """PRD §3.1: "within the same `road_segment_id`, no two `APPROVED`
        permits may sit within a 30-minute buffer of one another." Overlapping
        windows on different segments do not conflict.

        Design: Difficulty/resource_temporal_overlap/permit_buffered_window_conflict
        """
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        seg_a = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(name="A"), pc))
        seg_b = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(name="B"), pc))
        p1 = get_success_data(api.create_permit(
            seg_a["id"], create_permit_payload(), pc))
        get_success_data(api.submit_permit(p1["id"], pc))
        get_success_data(api.approve_permit(p1["id"], pc))

        # Identical window on a DIFFERENT segment must not conflict.
        p2 = get_success_data(api.create_permit(
            seg_b["id"], create_permit_payload(authority_name="County SO"), pc))
        get_success_data(api.submit_permit(p2["id"], pc))
        approved = validate_success(api.approve_permit(p2["id"], pc))
        assert approved["status"] == "APPROVED"


class TestPostureGates:
    def test_advance_blocked_without_segment_coverage(self, api,
                                                      race_director_headers):
        """PRD §3.1: "advancing the posture from `DRAFT` to `PERMITTED`
        requires at least one road segment to exist, and every segment must
        hold at least one `APPROVED` permit whose requested window covers the
        segment's planned closure — the permit's `requested_start` no later
        than the segment's `closure_start` and its `requested_end` no earlier
        than the segment's `closure_end`. A failure on either count is
        rejected with `ERR_SEGMENT_NOT_COVERED`."

        Design: Corner/validations/advance_blocked_without_segment_coverage
        """
        from test_helpers import TEST_USERS
        pc = TEST_USERS["permit_coordinator_headers"]
        event = create_event()
        segment = get_success_data(api.create_road_segment(
            event["id"], create_road_segment_payload(), pc))
        # Permit covers 06:00-10:00 but the closure runs to 12:00.
        permit = get_success_data(api.create_permit(
            segment["id"],
            create_permit_payload(requested_start="2026-10-15T06:00:00Z",
                                  requested_end="2026-10-15T10:00:00Z"),
            pc))
        get_success_data(api.submit_permit(permit["id"], pc))
        get_success_data(api.approve_permit(permit["id"], pc))

        resp = api.advance_event(event["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_COVERED.value)

        after = validate_success(api.get_event(event["id"], race_director_headers))
        assert after["posture"] == "DRAFT"

    def test_advance_blocked_when_station_not_ready(self, api,
                                                    race_director_headers):
        """PRD §3.3: "Publishing the event — advancing posture from
        `PERMITTED` to `PUBLISHED` — is where these logistics harden into a
        gate: at least one wave must be `OPEN` (`ERR_NO_OPEN_WAVE`), and every
        aid station of the event must be `READY` (`ERR_AID_STATION_NOT_READY`)."
        PRD §3.3: "Otherwise, if `allocated_water_units` is below
        `required_water_units`, the station is `WATER_SHORT`."

        Design: Corner/validations/advance_blocked_when_station_not_ready
        """
        from test_helpers import TEST_USERS, create_permitted_event
        vc = TEST_USERS["volunteer_coordinator_headers"]
        event = create_permitted_event(water_pool_units=500)
        get_success_data(api.create_wave(
            event["id"], create_wave_payload(), race_director_headers))
        station = get_success_data(api.create_aid_station(
            event["id"],
            create_aid_station_payload(required_volunteers=1,
                                       required_water_units=100),
            race_director_headers))
        assignment = get_success_data(api.create_volunteer_assignment(
            station["id"], create_volunteer_assignment_payload(), vc))
        get_success_data(api.confirm_volunteer_assignment(assignment["id"], vc))
        # No allocate-water call: station is staffed but WATER_SHORT.

        current = validate_success(api.get_aid_station(station["id"],
                                                       race_director_headers))
        assert current["readiness_status"] == "WATER_SHORT"

        resp = api.advance_event(event["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_AID_STATION_NOT_READY.value)
        after = validate_success(api.get_event(event["id"], race_director_headers))
        assert after["posture"] == "PERMITTED"

    def test_start_blocked_while_swim_decision_pending(self, api,
                                                       race_director_headers):
        """PRD §3.5: "For a `has_swim` event the swim decision must already be
        made — `swim_status` `SWIM_ON` or `SWIM_CANCELLED` — otherwise the
        start is rejected with `ERR_SWIM_DECISION_PENDING`."

        Design: Corner/validations/start_blocked_while_swim_decision_pending
        """
        from test_helpers import create_published_event
        ctx = create_published_event(has_swim=True, water_pool_units=100)
        resp = api.start_event(ctx["event"]["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_SWIM_DECISION_PENDING.value)
        after = validate_success(
            api.get_event(ctx["event"]["id"], race_director_headers))
        assert after["posture"] == "PUBLISHED"

    def test_cancelled_event_rejects_advance(self, api, race_director_headers):
        """PRD §2.6: "An Event's `posture` walks a one-way course — `DRAFT`,
        then `PERMITTED`, then `PUBLISHED`, then `LIVE`, and finally one of
        the terminal states `FINALIZED` or `CANCELLED`".
        PRD §2.10: "then state-machine from-state validity
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_event_rejects_advance
        """
        from test_helpers import create_permitted_event
        event = create_permitted_event()
        get_success_data(api.cancel_event(event["id"], race_director_headers,
                                          reason="hurricane"))
        resp = api.advance_event(event["id"], race_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_event(event["id"], race_director_headers))
        assert after["posture"] == "CANCELLED"

    def test_event_cancel_grants_full_refund(self, api, race_director_headers):
        """PRD §3.7: "Every registration in `ENTERED`, `PAID`, `CONFIRMED`,
        `WAITLISTED`, or `RACKED` is moved to `WITHDRAWN` at a full refund —
        the tier ladder and the processing fee are bypassed, and both
        `refund_estimate_cents` and `refund_final_cents` are set to the full
        `entry_fee_cents`".

        Design: Corner/endpoints/event_cancel_grants_full_refund
        """
        from test_helpers import create_permitted_event, create_paid_registration
        event = create_permitted_event()
        athlete, registration = create_paid_registration(
            event["id"], entry_fee_cents=20000)
        get_success_data(api.cancel_event(event["id"], race_director_headers,
                                          reason="wildfire smoke"))
        after = validate_success(
            api.get_registration(registration["id"], race_director_headers))
        assert after["status"] == "WITHDRAWN"
        assert after["refund_estimate_cents"] == 20000
        assert after["refund_final_cents"] == 20000, \
            "cancellation settles the full entry fee immediately, no fee"

    def test_event_parallel_dimensions_posture_x_swim(self, api,
                                                      race_director_headers):
        """PRD §2.6: "Independently of posture, the same Event carries a
        `swim_status` dimension with values `PENDING_DECISION`, `SWIM_ON`,
        `SWIM_CANCELLED`, and `NO_SWIM`... The two dimensions evolve in
        parallel: publishing the course says nothing about the swim, and a
        swim cancellation may arrive before or after racing begins".
        PRD §3.5: "Recording a new assessment supersedes the event's previous
        `RECORDED` assessment, moving it to `SUPERSEDED` (terminal), and flips
        the event's `swim_status` to match the new outcome."

        Design: Difficulty/non_linear_state_machine/event_parallel_dimensions_posture_x_swim
        """
        from test_helpers import (
            TEST_USERS, create_published_event, create_safety_assessment_payload,
        )
        ctx = create_published_event(has_swim=True, water_pool_units=1000)
        event_id = ctx["event"]["id"]
        first = get_success_data(api.create_safety_assessment(
            event_id, create_safety_assessment_payload(water_temp_celsius=20.0),
            race_director_headers))
        assert first["outcome"] == "SWIM_OK"

        second = get_success_data(api.create_safety_assessment(
            event_id,
            create_safety_assessment_payload(water_temp_celsius=10.0),
            TEST_USERS["referee_headers"]))
        assert second["outcome"] == "SWIM_CANCEL"

        event = validate_success(api.get_event(event_id, race_director_headers))
        assert event["posture"] == "PUBLISHED", \
            "safety cascade leaves posture unchanged"
        assert event["swim_status"] == "SWIM_CANCELLED", \
            "independent swim dimension flipped by the cancelling assessment"

        first_after = validate_success(
            api.get_safety_assessment(first["id"], race_director_headers))
        second_after = validate_success(
            api.get_safety_assessment(second["id"], race_director_headers))
        assert first_after["status"] == "SUPERSEDED"
        assert second_after["status"] == "RECORDED"

    def test_posture_advance_does_not_touch_swim_status(self, api,
                                                        race_director_headers):
        """PRD §2.6: "The two dimensions evolve in parallel: publishing the
        course says nothing about the swim".

        Design: Difficulty/non_linear_state_machine/event_parallel_dimensions_posture_x_swim
        """
        from test_helpers import create_permitted_event
        event = create_permitted_event(has_swim=True, water_pool_units=500)
        assert event["swim_status"] == "PENDING_DECISION"
        # Advance PERMITTED -> PUBLISHED requires an OPEN wave + READY station.
        get_success_data(api.create_wave(event["id"], create_wave_payload(),
                                         race_director_headers))
        from test_helpers import make_station_ready
        make_station_ready(event["id"])
        advanced = validate_success(api.advance_event(event["id"],
                                                      race_director_headers))
        assert advanced["posture"] == "PUBLISHED"
        assert advanced["swim_status"] == "PENDING_DECISION", \
            "posture advance must not flip the swim dimension"
