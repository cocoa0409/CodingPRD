"""Boundary precision tests: the OT threshold exactly-at value and the lodging
capacity equality boundary (PRD §3.4, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, certify_timesheet,
    create_lodging_block, create_lodging_assignment,
    setup_cleared_arrived_crew, setup_event_with_accepted_request,
    create_lodging_assignment_payload,
)


class TestOtThresholdExact480ZeroOt:
    def _certify_pair(self):
        """480-minute and 481-minute WORK days, both inside the premium window,
        crew carrying 35000/day equipment."""
        ctx = setup_cleared_arrived_crew(
            equipment_daily_rate_cents=35000, clock_after_arrival="2026-05-06T09:00:00Z")
        ts_a = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                          day_classification="WORK", reported_work_minutes=480)
        ts_b = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-05",
                                          day_classification="WORK", reported_work_minutes=481)
        ts_a = certify_timesheet(ts_a["id"], ctx["host"]["id"])
        ts_b = certify_timesheet(ts_b["id"], ctx["host"]["id"])
        return ts_a, ts_b

    def test_exactly_threshold_bills_zero_overtime(self):
        """PRD §3.6: "A day reporting exactly the overtime threshold bills zero
        overtime — overtime begins strictly beyond the threshold."

        Design: Difficulty/boundary_precision_check/ot_threshold_exact_480_zero_ot
        """
        ts_a, _ = self._certify_pair()
        # 480 min: reg 480 -> 96000; premium -> 105600; + equipment 35000 = 140600
        assert ts_a["certified_amount_cents"] == 140600

    def test_one_minute_beyond_threshold_bills_one_ot_minute(self):
        """PRD §3.6: "overtime minutes are whatever lies beyond
        `ot_threshold_minutes`, capped at the span between `ot_threshold_minutes`
        and `dt_threshold_minutes`" and "overtime minutes at the base rate scaled
        by `ot_multiplier_bps` ten-thousandths (the 15000 default yields
        time-and-a-half)"

        Design: Difficulty/boundary_precision_check/ot_threshold_exact_480_zero_ot
        """
        ts_a, ts_b = self._certify_pair()
        # 481 min: reg 96000 + round(1*12000*15000/(60*10000))=300 -> 96300;
        # premium -> 105930; + 35000 = 140930. The pair differs by exactly 330.
        assert ts_b["certified_amount_cents"] == 140930
        assert ts_b["certified_amount_cents"] - ts_a["certified_amount_cents"] == 330


class TestLodgingCapacityEqualityAllowed:
    def _setup_two_crews_and_block(self):
        ctx = setup_event_with_accepted_request()
        crew1 = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
        crew2 = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"],
                            crew_type="TREE", home_base="Depot 9",
                            roster=[{"member_ref": "M2", "member_role": "foreman"}])
        block = create_lodging_block(ctx["event"]["id"], ctx["host"]["id"],
                                     block_code="BLK-2", total_rooms=2)
        ctx.update({"crew1": crew1, "crew2": crew2, "block": block})
        return ctx

    def test_assignment_reaching_exact_capacity_is_allowed(self):
        """PRD §3.4: "the block must have room, meaning `assigned_rooms` plus
        the new `room_count` may not exceed `total_rooms` — equality is allowed,
        and any excess is `ERR_LODGING_CAPACITY_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/lodging_capacity_equality_allowed
        """
        ctx = self._setup_two_crews_and_block()
        resp = api_client.create_lodging_assignment(
            create_lodging_assignment_payload(
                block_id=ctx["block"]["id"], crew_id=ctx["crew1"]["id"], room_count=2),
            make_host_coordinator_headers(ctx["host"]["id"]))
        asg = validate_success(resp, expected_status=201)
        assert asg["status"] == "RESERVED"
        resp = api_client.get_lodging_block(ctx["block"]["id"], make_program_admin_headers())
        assert validate_success(resp)["assigned_rooms"] == 2

    def test_one_room_beyond_capacity_is_rejected(self):
        """PRD §3.4: "equality is allowed, and any excess is
        `ERR_LODGING_CAPACITY_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/lodging_capacity_equality_allowed
        """
        ctx = self._setup_two_crews_and_block()
        create_lodging_assignment(ctx["block"]["id"], ctx["crew1"]["id"], ctx["host"]["id"],
                                  room_count=2)
        resp = api_client.create_lodging_assignment(
            create_lodging_assignment_payload(
                block_id=ctx["block"]["id"], crew_id=ctx["crew2"]["id"], room_count=1),
            make_host_coordinator_headers(ctx["host"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LODGING_CAPACITY_EXCEEDED)
        resp = api_client.get_lodging_block(ctx["block"]["id"], make_program_admin_headers())
        assert validate_success(resp)["assigned_rooms"] == 2
