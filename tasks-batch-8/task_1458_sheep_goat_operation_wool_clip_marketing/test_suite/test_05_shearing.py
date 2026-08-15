"""Shearing crews, bookings, buffer rule, feasibility, clip intake."""
from test_helpers import (
    ApiErrorId,
    assert_wool_clip,
    create_completed_clip,
    create_crew,
    create_flock,
    create_shearing_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCrewBookings:

    def test_shearing_crew_24h_buffer_forbids_adjacency(self, api, ranch_manager_headers):
        """PRD §3.3: "the sanitation-buffer overlap rule: the booking is rejected
        with `ERR_CREW_OVERLAP` (HTTP 409) when another event on the same crew
        in `SCHEDULED` or `IN_PROGRESS` status is separated from the new window
        by less than a full 24-hour buffer on both sides — the booking survives
        only if it starts at or later than 24 hours after the other event's
        end, or its own end is at or earlier than 24 hours before the other
        event's start. Unlike pasture moves, mere adjacency is forbidden here:
        back-to-back bookings without a 24-hour gap fail."

        Design: Difficulty/resource_temporal_overlap/shearing_crew_24h_buffer_forbids_adjacency
        """
        flock = create_flock(flock_name="Buffer Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Crew Buf", head_per_day_capacity=500, daily_rate_cents=60000)
        api.create_shearing_event(
            create_shearing_event_payload(
                flock_id=flock["id"], crew_id=crew["id"],
                scheduled_start="2026-09-01T00:00:00Z", scheduled_end="2026-09-03T00:00:00Z",
                expected_head=500), ranch_manager_headers)

        # Adjacent booking starting exactly at the first booking's end -> conflict.
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-09-03T00:00:00Z", "scheduled_end": "2026-09-05T00:00:00Z",
            "expected_head": 400,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP.value, expected_status=409)

        # Booking starting exactly 24h after the first event's end -> accepted.
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-09-04T00:00:00Z", "scheduled_end": "2026-09-06T00:00:00Z",
            "expected_head": 400,
        }, ranch_manager_headers)
        event = validate_success(resp, expected_status=201)
        assert event["shearing_status"] == "SCHEDULED"

    def test_shearing_crew_buffer_inside_24h_rejected(self, api, ranch_manager_headers):
        """PRD §3.3: "the booking survives only if it starts at or later than 24
        hours after the other event's end, or its own end is at or earlier than
        24 hours before the other event's start."

        Design: Difficulty/resource_temporal_overlap/shearing_crew_24h_buffer_forbids_adjacency
        """
        flock = create_flock(flock_name="Buffer2 Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Crew Buf2", head_per_day_capacity=500, daily_rate_cents=60000)
        api.create_shearing_event(
            create_shearing_event_payload(
                flock_id=flock["id"], crew_id=crew["id"],
                scheduled_start="2026-09-01T00:00:00Z", scheduled_end="2026-09-03T00:00:00Z",
                expected_head=500), ranch_manager_headers)
        # Starts 23 hours after the first event's end: inside the buffer.
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-09-03T23:00:00Z", "scheduled_end": "2026-09-05T00:00:00Z",
            "expected_head": 400,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP.value, expected_status=409)

    def test_shearing_window_infeasible_and_feasibility_boundary(self, api, ranch_manager_headers):
        """PRD §3.3: "the feasibility rule: the number of whole calendar days
        contained in the half-open booking window, multiplied by the crew's
        `head_per_day_capacity`, must be at least `expected_head`, else
        `ERR_SHEARING_WINDOW_INFEASIBLE` (HTTP 422)."

        Design: Corner/endpoints/shearing_window_infeasible_and_feasibility_boundary
        """
        flock = create_flock(flock_name="Feasible Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Slow Crew", head_per_day_capacity=100, daily_rate_cents=20000)
        # 2 whole days * 100/day == 200 < 201 -> infeasible.
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-08-03T00:00:00Z", "scheduled_end": "2026-08-05T00:00:00Z",
            "expected_head": 201,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SHEARING_WINDOW_INFEASIBLE.value, expected_status=422)
        # Exact equality (200 == 2*100) books successfully.
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-08-10T00:00:00Z", "scheduled_end": "2026-08-12T00:00:00Z",
            "expected_head": 200,
        }, ranch_manager_headers)
        event = validate_success(resp, expected_status=201)
        assert event["shearing_status"] == "SCHEDULED"

    def test_crew_inactive_scheduling_rejected(self, api, ranch_manager_headers):
        """PRD §3.3: "First, the crew must be `ACTIVE`, else `ERR_CREW_INACTIVE`
        (HTTP 409)."

        Design: Corner/endpoints/crew_inactive_scheduling_rejected
        """
        flock = create_flock(flock_name="Inactive Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Retired Crew")
        resp = api.deactivate_shearing_crew(crew["id"], ranch_manager_headers)
        validate_success(resp)
        resp = api.create_shearing_event({
            "flock_id": flock["id"], "crew_id": crew["id"],
            "scheduled_start": "2026-08-03T00:00:00Z", "scheduled_end": "2026-08-05T00:00:00Z",
            "expected_head": 400,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_INACTIVE.value, expected_status=409)

    def test_crew_busy_deactivate_rejected(self, api, ranch_manager_headers):
        """PRD §3.3: "Taking a crew off the board (`ACTIVE -> INACTIVE`) is
        blocked while any of its events is still `SCHEDULED` or `IN_PROGRESS`,
        surfacing `ERR_CREW_BUSY` (HTTP 409)."

        Design: Corner/endpoints/crew_busy_deactivate_rejected
        """
        flock = create_flock(flock_name="BusyCrew Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Booked Crew")
        api.create_shearing_event(
            create_shearing_event_payload(flock_id=flock["id"], crew_id=crew["id"]),
            ranch_manager_headers)
        resp = api.deactivate_shearing_crew(crew["id"], ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_BUSY.value, expected_status=409)
        crew = validate_success(api.get_shearing_crew(crew["id"], ranch_manager_headers))
        assert crew["crew_status"] == "ACTIVE"


class TestShearingCompletion:

    def test_shearing_complete_from_scheduled_rejected(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.3: "Completion (`IN_PROGRESS -> COMPLETED`) records the floor
        tallies" and "any other transition is rejected with
        `ERR_SHEARING_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "The clip is discoverable by filtering the clip list by
        `shearing_event_id`, which returns an array of length zero or one; the
        list also filters by `flock_id`."

        Design: Corner/state_machines/shearing_complete_from_scheduled_rejected
        """
        flock = create_flock(flock_name="Shear Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Crew S")
        event = validate_success(api.create_shearing_event(
            create_shearing_event_payload(flock_id=flock["id"], crew_id=crew["id"]),
            ranch_manager_headers), expected_status=201)
        resp = api.complete_shearing_event(event["id"], {
            "shorn_head_count": 400, "greasy_weight_lbs": 200.0, "skirtings_weight_lbs": 20.0,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_SHEARING_INVALID_STATE.value, expected_status=409)
        event = validate_success(api.get_shearing_event(event["id"], ranch_manager_headers))
        assert event["shearing_status"] == "SCHEDULED"
        _, meta = validate_paginated(
            api.list_wool_clips(ranch_manager_headers, params={"shearing_event_id": event["id"]}))
        assert meta["total_count"] == 0, "no clip created without completion"

    def test_clip_discovery_by_shearing_event(self, api, ranch_manager_headers):
        """PRD §3.3: "Completion fires the clip cascade: exactly one wool clip
        is created per completed shearing event, keyed by `shearing_event_id`
        (the relationship is one-to-one), with `flock_id` copied from the event
        and `greasy_weight_lbs` and `skirtings_weight_lbs` copied from the
        tallies. The clip is discoverable by filtering the clip list by
        `shearing_event_id`, which returns an array of length zero or one".
        PRD §3.3: "`UNGRADED` when the clip has no lots at all".

        Design: Corner/endpoints/clip_discovery_by_shearing_event
        """
        flock = create_flock(flock_name="Clip Ranch", species="SHEEP", baseline_headcount=500)
        crew = create_crew(crew_name="Crew CL")
        event = validate_success(api.create_shearing_event(
            create_shearing_event_payload(flock_id=flock["id"], crew_id=crew["id"]),
            ranch_manager_headers), expected_status=201)
        _, meta = validate_paginated(
            api.list_wool_clips(ranch_manager_headers, params={"shearing_event_id": event["id"]}))
        assert meta["total_count"] == 0, "no clip before completion"

        clip, _event, _crew = None, None, None
        # Drive the event to completion on the same event id.
        from test_helpers import set_clock
        set_clock("2026-08-03T00:00:00Z")
        validate_success(api.transition_shearing_event(event["id"], {"to": "IN_PROGRESS"}, ranch_manager_headers))
        validate_success(api.complete_shearing_event(event["id"], {
            "shorn_head_count": 400, "greasy_weight_lbs": 200.0, "skirtings_weight_lbs": 20.0,
        }, ranch_manager_headers))

        clips, meta = validate_paginated(
            api.list_wool_clips(ranch_manager_headers, params={"shearing_event_id": event["id"]}))
        assert meta["total_count"] == 1, "exactly one clip per completed shearing event"
        assert len(clips) == 1
        clip = clips[0]
        assert_wool_clip(clip)
        assert clip["flock_id"] == flock["id"]
        assert clip["greasy_weight_lbs"] == 200.0
        assert clip["skirtings_weight_lbs"] == 20.0
        assert clip["marketing_posture"] == "UNGRADED", "no lots yet -> UNGRADED"
