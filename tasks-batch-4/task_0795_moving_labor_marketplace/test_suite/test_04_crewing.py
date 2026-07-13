"""Crewing: assignment approval gate, crew-slot capacity, helper travel-buffer overlap,
truck closed-interval overlap, validation precedence, truck assignment, and no-shows."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_config, create_booked_job, create_approved_helper, create_helper,
    assign_helper, check_in, vet_helper, create_truck,
    create_assignment_payload, assign_truck_payload,
    make_customer_headers, make_helper_headers, ADMIN, DISPATCHER, api_client,
)


class TestCrewSlotBoundary:
    """Design: Difficulty/boundary_precision_check/crew_slots_full_boundary"""

    def _crew2_job_with_three_helpers(self, api):
        rate_card, policy, customer = create_config(api)
        h1 = create_approved_helper(api, email="h1@x.com")
        h2 = create_approved_helper(api, email="h2@x.com")
        h3 = create_approved_helper(api, email="h3@x.com")
        booked, _quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=2, estimated_hours=3.0,
            window_start="2026-03-11T09:00:00Z", window_end="2026-03-11T12:00:00Z",
        )
        return booked, (h1, h2, h3)

    def test_assignments_up_to_crew_size_accepted(self, api):
        """PRD §3.5: "The number of the job's assignments in the count-eligible states
        (`ASSIGNED`, `CHECKED_IN`, or `CHECKED_OUT`) may not exceed the job's `crew_size`".

        For crew_size 2, the first two assignments are accepted in ASSIGNED.

        Design: Difficulty/boundary_precision_check/crew_slots_full_boundary
        """
        booked, (h1, h2, _h3) = self._crew2_job_with_three_helpers(api)
        a1 = assign_helper(api, booked["id"], h1["id"])
        a2 = assign_helper(api, booked["id"], h2["id"])
        assert a1["status"] == "ASSIGNED"
        assert a2["status"] == "ASSIGNED"

    def test_assignment_beyond_crew_size_rejected(self, api):
        """PRD §3.5: "an attempt to add one beyond that is rejected with `ERR_CREW_FULL`."

        The third assignment on a crew_size-2 job is rejected.

        Design: Difficulty/boundary_precision_check/crew_slots_full_boundary
        """
        booked, (h1, h2, h3) = self._crew2_job_with_three_helpers(api)
        assign_helper(api, booked["id"], h1["id"])
        assign_helper(api, booked["id"], h2["id"])
        resp = api.create_assignment(create_assignment_payload(booked["id"], h3["id"]), DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CREW_FULL)


class TestStartRequiresCheckedInCrew:
    """Design: Difficulty/cross_entity_state_dependency/start_requires_checked_in_crew"""

    def _booked_with_assigned_but_not_checked_in(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api, email="h1@x.com")
        booked, _quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0,
            window_start="2026-03-11T09:00:00Z", window_end="2026-03-11T12:00:00Z",
        )
        assign_helper(api, booked["id"], helper["id"])
        return booked

    def test_start_without_checked_in_crew_rejected(self, api):
        """PRD §3.6: "Starting requires that at least one assignment for the job be in status
        `CHECKED_IN`; if no crew member has checked in, the request is rejected with
        `ERR_NO_CREW_CHECKED_IN`."

        Design: Difficulty/cross_entity_state_dependency/start_requires_checked_in_crew
        """
        booked = self._booked_with_assigned_but_not_checked_in(api)
        resp = api.start_job(booked["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NO_CREW_CHECKED_IN)

    def test_job_stays_booked_when_start_blocked(self, api):
        """PRD §3.6: "A dispatcher starts a `BOOKED` job, transitioning it
        `BOOKED → IN_PROGRESS`." The blocked start leaves the job in BOOKED.

        Design: Difficulty/cross_entity_state_dependency/start_requires_checked_in_crew
        """
        booked = self._booked_with_assigned_but_not_checked_in(api)
        api.start_job(booked["id"], DISPATCHER)
        after = validate_success(api.get_job(booked["id"], ADMIN))
        assert after["status"] == "BOOKED"


class TestAssignRequiresApprovedHelper:
    """Design: Difficulty/cross_entity_state_dependency/assign_requires_helper_approved"""

    def _booked_job_and_pending_helper(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_helper(api, email="hn@x.com")  # left PENDING_REVIEW
        booked, _quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0,
            window_start="2026-03-11T09:00:00Z", window_end="2026-03-11T12:00:00Z",
        )
        return booked, helper

    def test_assign_pending_helper_rejected(self, api):
        """PRD §3.5: "If the helper's `vetting_status` is anything other than `APPROVED`, the
        request is rejected with `ERR_HELPER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/assign_requires_helper_approved
        """
        booked, helper = self._booked_job_and_pending_helper(api)
        resp = api.create_assignment(create_assignment_payload(booked["id"], helper["id"]), DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_HELPER_NOT_APPROVED)

    def test_no_assignment_created_for_pending_helper(self, api):
        """PRD §3.2: "A helper in `PENDING_REVIEW` may be moved with an `APPROVE` decision to
        `APPROVED`, which makes them eligible to be assigned". A rejected assignment on a
        PENDING_REVIEW helper leaves no assignment on the job.

        Design: Difficulty/cross_entity_state_dependency/assign_requires_helper_approved
        """
        booked, helper = self._booked_job_and_pending_helper(api)
        api.create_assignment(create_assignment_payload(booked["id"], helper["id"]), DISPATCHER)
        listed, _meta = _list(api.list_assignments(ADMIN, params={"job_id": booked["id"]}))
        assert listed == []


class TestHelperTravelBufferOverlap:
    """Design: Difficulty/resource_temporal_overlap/helper_overlap_with_travel_buffer"""

    def _helper_on_morning_job(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api, email="hb@x.com")
        job1, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0,
            window_start="2026-03-10T09:00:00Z", window_end="2026-03-10T11:00:00Z",
        )
        assign_helper(api, job1["id"], helper["id"])
        return rate_card, policy, customer, helper

    def test_overlap_within_travel_buffer_rejected(self, api):
        """PRD §3.5: "the helper must have no other non-released assignment whose job window
        overlaps the target job's window, where overlap is judged on a half-open interval
        from window start up to but not including window end, extended by a 60-minute travel
        buffer; a conflict is rejected with `ERR_HELPER_UNAVAILABLE`."

        A second job starting 30 minutes after the first ends collides through the buffer.

        Design: Difficulty/resource_temporal_overlap/helper_overlap_with_travel_buffer
        """
        rate_card, policy, customer, helper = self._helper_on_morning_job(api)
        job2, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=1.5,
            window_start="2026-03-10T11:30:00Z", window_end="2026-03-10T13:00:00Z",
        )
        resp = api.create_assignment(create_assignment_payload(job2["id"], helper["id"]), DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_HELPER_UNAVAILABLE)

    def test_assignment_clear_of_travel_buffer_succeeds(self, api):
        """PRD §3.5: "the helper must have no other non-released assignment whose job window
        overlaps the target job's window, where overlap is judged on a half-open interval
        from window start up to but not including window end, extended by a 60-minute travel
        buffer".

        A second job starting two hours after the first ends is clear of the buffer and the
        assignment is accepted.

        Design: Difficulty/resource_temporal_overlap/helper_overlap_with_travel_buffer
        """
        rate_card, policy, customer, helper = self._helper_on_morning_job(api)
        job3, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0,
            window_start="2026-03-10T13:00:00Z", window_end="2026-03-10T15:00:00Z",
        )
        assignment = validate_success(
            api.create_assignment(create_assignment_payload(job3["id"], helper["id"]), DISPATCHER), 201,
        )
        assert assignment["status"] == "ASSIGNED"


class TestTruckClosedIntervalOverlap:
    """Design: Difficulty/resource_temporal_overlap/truck_overlap_touching_endpoints"""

    def _truck_on_first_job_and_touching_second(self, api):
        rate_card, policy, customer = create_config(api)
        truck = create_truck(api)
        job1, _q1 = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0, truck_required=True,
            window_start="2026-03-12T09:00:00Z", window_end="2026-03-12T11:00:00Z",
        )
        validate_success(api.assign_truck(job1["id"], assign_truck_payload(truck["id"]), DISPATCHER))
        job2, _q2 = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0, truck_required=True,
            window_start="2026-03-12T11:00:00Z", window_end="2026-03-12T13:00:00Z",
        )
        return truck, job2

    def test_touching_endpoints_reject_truck_assignment(self, api):
        """PRD §3.6: "A truck may be assigned only if it has no other job in status `BOOKED`
        or `IN_PROGRESS` whose window collides with the target job's window; unlike the
        helper check, the truck overlap is judged on the closed interval between window start
        and window end with no travel buffer. A collision is rejected with
        `ERR_TRUCK_UNAVAILABLE`."

        Windows sharing an endpoint (11:00) collide under closed intervals.

        Design: Difficulty/resource_temporal_overlap/truck_overlap_touching_endpoints
        """
        truck, job2 = self._truck_on_first_job_and_touching_second(api)
        resp = api.assign_truck(job2["id"], assign_truck_payload(truck["id"]), DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_TRUCK_UNAVAILABLE)

    def test_second_job_truck_unset_after_collision(self, api):
        """PRD §3.6: "Before or during a booked job, a dispatcher may attach a truck, setting
        the job's `truck_id`." A rejected truck assignment leaves the second job's truck_id
        unset.

        Design: Difficulty/resource_temporal_overlap/truck_overlap_touching_endpoints
        """
        truck, job2 = self._truck_on_first_job_and_touching_second(api)
        api.assign_truck(job2["id"], assign_truck_payload(truck["id"]), DISPATCHER)
        after = validate_success(api.get_job(job2["id"], ADMIN))
        assert after["truck_id"] is None


class TestAssignApprovalBeatsAvailability:
    """Design: Difficulty/priority_pair_validation_conflict/assign_not_approved_beats_helper_unavailable"""

    def _suspended_helper_and_overlapping_job(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api, email="hp@x.com")
        job1, _q1 = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0,
            window_start="2026-03-10T09:00:00Z", window_end="2026-03-10T11:00:00Z",
        )
        asg1 = assign_helper(api, job1["id"], helper["id"])
        check_in(api, asg1["id"], helper["id"])         # CHECKED_IN survives suspension
        vet_helper(api, helper["id"], "SUSPEND")        # helper now SUSPENDED
        job2, _q2 = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=2.0,
            window_start="2026-03-10T09:30:00Z", window_end="2026-03-10T11:30:00Z",
        )
        return helper, job2

    def test_not_approved_error_preempts_unavailable(self, api):
        """PRD §3.5: "Several checks guard assignment creation, evaluated in this order after
        the standard existence checks: the helper must be approved, then the job's crew slots
        must not be full, then the helper must be available in the requested window."

        A suspended helper who also has an overlapping CHECKED_IN assignment fails the
        approval check first, so ERR_HELPER_NOT_APPROVED is returned.

        Design: Difficulty/priority_pair_validation_conflict/assign_not_approved_beats_helper_unavailable
        """
        helper, job2 = self._suspended_helper_and_overlapping_job(api)
        resp = api.create_assignment(create_assignment_payload(job2["id"], helper["id"]), DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_HELPER_NOT_APPROVED)

    def test_availability_error_not_returned_first(self, api):
        """PRD §3.5: "If the helper's `vetting_status` is anything other than `APPROVED`, the
        request is rejected with `ERR_HELPER_NOT_APPROVED`." The approval check runs before
        the availability check, so the returned error is not the availability error.

        Design: Difficulty/priority_pair_validation_conflict/assign_not_approved_beats_helper_unavailable
        """
        helper, job2 = self._suspended_helper_and_overlapping_job(api)
        resp = api.create_assignment(create_assignment_payload(job2["id"], helper["id"]), DISPATCHER)
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_HELPER_UNAVAILABLE.value
        assert body["data"]["error_id"] == ApiErrorId.ERR_HELPER_NOT_APPROVED.value


def test_assign_truck_sets_job_truck_id(api):
    """PRD §3.6: "Before or during a booked job, a dispatcher may attach a truck, setting the
    job's `truck_id`."

    Design: Corner/endpoints/assign_truck_sets_truck_id
    """
    rate_card, policy, customer = create_config(api)
    truck = create_truck(api)
    booked, _q = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=2.0, truck_required=True,
        window_start="2026-03-12T09:00:00Z", window_end="2026-03-12T11:00:00Z",
    )
    updated = validate_success(api.assign_truck(booked["id"], assign_truck_payload(truck["id"]), DISPATCHER))
    assert updated["truck_id"] == truck["id"]


def test_no_show_increments_counter_and_drops_active_count(api):
    """PRD §3.5: "A dispatcher may instead mark an `ASSIGNED` helper as a no-show,
    transitioning the assignment `ASSIGNED → NO_SHOW`; this recomputes the helper's
    `no_show_count` (an increment) and their `active_assignment_count` (a decrement, since
    `NO_SHOW` is not a count-eligible state)."

    Design: Corner/state_machines/no_show_marks_helper
    """
    rate_card, policy, customer = create_config(api)
    helper = create_approved_helper(api, email="hn@x.com")
    booked, _q = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=3.0,
        window_start="2026-03-11T09:00:00Z", window_end="2026-03-11T12:00:00Z",
    )
    assignment = assign_helper(api, booked["id"], helper["id"])
    marked = validate_success(api.mark_no_show(assignment["id"], DISPATCHER))
    assert marked["status"] == "NO_SHOW"
    refreshed = validate_success(api.get_helper(helper["id"], ADMIN))
    assert refreshed["no_show_count"] == 1
    assert refreshed["active_assignment_count"] == 0


def _list(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)
