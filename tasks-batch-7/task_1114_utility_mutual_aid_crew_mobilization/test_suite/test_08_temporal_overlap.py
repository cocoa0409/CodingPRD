"""Resource temporal-overlap tests: half-open lodging stay intervals versus
closed-interval schedule coverage windows (PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, create_lodging_block,
    create_lodging_assignment, setup_event_active,
    setup_event_with_accepted_request,
    create_lodging_assignment_payload, create_billing_rate_schedule_payload,
)


class TestLodgingHalfOpenAdjacencyAllowed:
    def _setup_crew_block_first_stay(self):
        ctx = setup_event_with_accepted_request()
        crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
        block = create_lodging_block(ctx["event"]["id"], ctx["host"]["id"],
                                     block_code="BLK-5", total_rooms=5)
        asg1 = create_lodging_assignment(block["id"], crew["id"], ctx["host"]["id"],
                                         check_in_date="2026-05-03",
                                         check_out_date="2026-05-06")
        ctx.update({"crew": crew, "block": block, "asg1": asg1})
        return ctx

    def test_adjacent_stay_touching_at_checkout_is_accepted(self):
        """PRD §3.4: "an assignment names the `block_id` and `crew_id`, the
        `room_count`, and a stay interval from `check_in_date` to
        `check_out_date` under half-open semantics — the crew occupies the
        check-in night through the night before check-out" and "back-to-back
        stays that merely touch at a boundary date are permitted."

        Design: Difficulty/resource_temporal_overlap/lodging_half_open_adjacency_allowed
        """
        ctx = self._setup_crew_block_first_stay()
        resp = api_client.create_lodging_assignment(
            create_lodging_assignment_payload(
                block_id=ctx["block"]["id"], crew_id=ctx["crew"]["id"], room_count=1,
                check_in_date="2026-05-06", check_out_date="2026-05-09"),
            make_host_coordinator_headers(ctx["host"]["id"]))
        asg2 = validate_success(resp, expected_status=201)
        assert asg2["status"] == "RESERVED"

    def test_one_day_intersection_is_rejected(self):
        """PRD §3.4: "the same crew must not already hold a non-cancelled
        assignment whose half-open interval intersects the new one — a new stay
        whose `check_in_date` falls before an existing stay's `check_out_date`
        while the existing stay's `check_in_date` falls before the new
        `check_out_date` conflicts and is rejected with `ERR_LODGING_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/lodging_half_open_adjacency_allowed
        """
        ctx = self._setup_crew_block_first_stay()
        resp = api_client.create_lodging_assignment(
            create_lodging_assignment_payload(
                block_id=ctx["block"]["id"], crew_id=ctx["crew"]["id"], room_count=1,
                check_in_date="2026-05-05", check_out_date="2026-05-08"),
            make_host_coordinator_headers(ctx["host"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LODGING_OVERLAP)


class TestScheduleClosedIntervalBoundaryConflict:
    def _setup_published_s1_and_two_drafts(self):
        set_clock("2026-05-01T08:00:00Z")
        host, rsp, event = setup_event_active(set_clock_first=False)
        s1 = create_and_publish_schedule(event["id"], rsp["id"])
        s2_payload = create_billing_rate_schedule_payload(
            event_id=event["id"], effective_start_date="2026-05-31",
            effective_end_date="2026-06-30",
            rate_lines=[{"crew_type": "LINE", "hourly_rate_cents": 12500}])
        resp = api_client.create_billing_rate_schedule(
            s2_payload, make_responding_coordinator_headers(rsp["id"]))
        assert resp.status_code == 201, f"Setup failed creating S2: {resp.text}"
        s2 = get_success_data(resp)
        s3_payload = create_billing_rate_schedule_payload(
            event_id=event["id"], effective_start_date="2026-06-01",
            effective_end_date="2026-06-30",
            rate_lines=[{"crew_type": "LINE", "hourly_rate_cents": 12500}])
        resp = api_client.create_billing_rate_schedule(
            s3_payload, make_responding_coordinator_headers(rsp["id"]))
        assert resp.status_code == 201, f"Setup failed creating S3: {resp.text}"
        s3 = get_success_data(resp)
        return host, rsp, event, s1, s2, s3

    def test_shared_inclusive_end_date_conflicts(self):
        """PRD §3.2: "a closed-interval overlap check: no other schedule for the
        same event and responding utility in `PUBLISHED` or `LOCKED` status may
        have a coverage window intersecting this one, and because both ends are
        inclusive an existing window ending 2026-05-31 conflicts with a new
        window starting 2026-05-31; a violation is rejected with
        `ERR_SCHEDULE_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/schedule_closed_interval_boundary_conflict
        """
        host, rsp, event, s1, s2, s3 = self._setup_published_s1_and_two_drafts()
        resp = api_client.publish_billing_rate_schedule(
            s2["id"], {}, make_responding_coordinator_headers(rsp["id"]))
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP)
        resp = api_client.get_billing_rate_schedule(s2["id"], make_program_admin_headers())
        assert validate_success(resp)["status"] == "DRAFT"

    def test_window_starting_the_next_day_is_accepted(self):
        """PRD §3.2: "The coverage window runs from `effective_start_date`
        through `effective_end_date`, both bounds inclusive — a closed
        interval." — a new window starting the day after the existing window's
        inclusive end does not intersect it.

        Design: Difficulty/resource_temporal_overlap/schedule_closed_interval_boundary_conflict
        """
        host, rsp, event, s1, s2, s3 = self._setup_published_s1_and_two_drafts()
        resp = api_client.publish_billing_rate_schedule(
            s3["id"], {}, make_responding_coordinator_headers(rsp["id"]))
        schedule = validate_success(resp)
        assert schedule["status"] == "PUBLISHED"
