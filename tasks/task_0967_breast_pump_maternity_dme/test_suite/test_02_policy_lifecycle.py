"""Policy benefit-period overlap, termination cascade, and the ACTIVE gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_policy_payload,
    get_success_data,
    setup_delivered_with_schedule,
    setup_pending_order_verified,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPolicyPeriodOverlap:
    def test_overlapping_benefit_period_rejected(self, api, platform_admin_headers,
                                                 care_coordinator_headers):
        """PRD §2.7: "Among a single member's `ACTIVE` policies, benefit periods may never
        overlap; adjacency is permitted, meaning a new policy whose `benefit_period_start`
        equals an existing policy's `benefit_period_end` is allowed. An overlapping
        creation is rejected with `ERR_POLICY_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/policy_benefit_period_half_open_overlap
        """
        member = get_success_data(
            api.create_member(
                {"full_name": "Ovl Mem", "email": "ovl@x.com",
                 "date_of_birth": "1991-06-16", "shipping_address": "18 Sycamore St"},
                care_coordinator_headers,
            )
        )
        validate_success(
            api.create_policy(create_policy_payload(member["id"]), platform_admin_headers), 201
        )
        res = api.create_policy(
            create_policy_payload(
                member["id"], payer_name="PayerY", plan_type="MEDICAID",
                benefit_period_start="2026-06-01", benefit_period_end="2027-06-01",
            ),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_PERIOD_OVERLAP, expected_status=409)

    def test_adjacent_benefit_period_permitted(self, api, platform_admin_headers,
                                               care_coordinator_headers):
        """PRD §2.7: "adjacency is permitted, meaning a new policy whose
        `benefit_period_start` equals an existing policy's `benefit_period_end` is allowed."

        Design: Difficulty/resource_temporal_overlap/policy_benefit_period_half_open_overlap
        """
        member = get_success_data(
            api.create_member(
                {"full_name": "Adj Mem", "email": "adj@x.com",
                 "date_of_birth": "1991-06-16", "shipping_address": "18 Sycamore St"},
                care_coordinator_headers,
            )
        )
        validate_success(
            api.create_policy(create_policy_payload(member["id"]), platform_admin_headers), 201
        )
        res = api.create_policy(
            create_policy_payload(
                member["id"], payer_name="PayerY", plan_type="MEDICAID",
                benefit_period_start="2027-01-01", benefit_period_end="2028-01-01",
            ),
            platform_admin_headers,
        )
        policy_b = validate_success(res, 201)
        assert policy_b["benefit_period_start"] == "2027-01-01"

        data, meta = validate_paginated(
            api.list_policies(platform_admin_headers, params={"member_id": member["id"]})
        )
        assert meta["total_count"] == 2


class TestPolicyTerminationCascade:
    def test_terminate_policy_ends_active_schedules(self, api, platform_admin_headers,
                                                    care_coordinator_headers):
        """PRD §3.8: "Terminating moves the policy `ACTIVE → TERMINATED` (its terminal
        state) and sweeps downstream: every `ResupplySchedule` whose originating pump order
        bills this policy and whose status is `ACTIVE` or `SUSPENDED` transitions to
        `ENDED`, and each affected member's `active_schedule_count` and `next_resupply_date`
        are recomputed."

        Design: Corner/state_machines/policy_terminate_ends_schedules
        """
        ctx = setup_delivered_with_schedule()
        policy = ctx["policy"]
        schedule = ctx["schedule"]
        assert schedule["status"] == "ACTIVE"

        res = api.terminate_policy(policy["id"], platform_admin_headers)
        terminated = validate_success(res, 200)
        assert terminated["status"] == "TERMINATED"

        schedule_after = validate_success(
            api.get_resupply_schedule(schedule["id"], care_coordinator_headers), 200
        )
        assert schedule_after["status"] == "ENDED"

    def test_terminate_policy_zeroes_member_resupply_aggregates(self, api, platform_admin_headers,
                                                                care_coordinator_headers):
        """PRD §2.10: "Two member-level aggregates are maintained continuously:
        `active_schedule_count` (the number of the member's resupply schedules currently
        `ACTIVE`) and `next_resupply_date` (the earliest `next_eligible_date` among those
        schedules, or null when none are `ACTIVE`). Both are recomputed whenever a schedule
        is created, suspended, resumed, or ended."

        Design: Corner/state_machines/policy_terminate_ends_schedules
        """
        ctx = setup_delivered_with_schedule()
        validate_success(api.terminate_policy(ctx["policy"]["id"], platform_admin_headers), 200)

        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["active_schedule_count"] == 0
        assert member["next_resupply_date"] is None


class TestPolicyActiveGate:
    def test_order_create_against_terminated_policy_rejected(self, api, platform_admin_headers,
                                                             care_coordinator_headers):
        """PRD §3.8: "After termination the policy fails the `ACTIVE` gate everywhere —
        new orders and qualifications against it are rejected with
        `ERR_POLICY_NOT_ACTIVE`" while its history remains readable.

        Design: Corner/validations/policy_not_active_blocks_order_create
        """
        ctx = setup_pending_order_verified()
        validate_success(api.terminate_policy(ctx["policy"]["id"], platform_admin_headers), 200)

        res = api.create_pump_order(
            {
                "member_id": ctx["member"]["id"],
                "policy_id": ctx["policy"]["id"],
                "prescription_id": ctx["rx"]["id"],
                "pump_item_id": ctx["pump"]["id"],
                "shipping_address": "15 V St",
            },
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE, expected_status=409)
