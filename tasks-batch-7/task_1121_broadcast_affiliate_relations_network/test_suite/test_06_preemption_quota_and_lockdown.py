"""Preemption quota and SWEEP_LOCKDOWN priority interaction.

Covers difficulty priority_pair_validation_conflict and corner
preemption_quota_boundary_exactly_10_percent.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    setup_basic_scenario,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_preemption_request,
    create_program,
    drive_network_into_sweep_lockdown,
)


def _approve(nid, sid, pr_id, nar):
    get_success_data(api_client.begin_review_preemption(nid, sid, pr_id, nar))
    return api_client.approve_preemption(nid, sid, pr_id, nar)


class TestPreemptionQuota:
    def test_quota_boundary_allows_exactly_ten_percent(self, api):
        """PRD §3.3: "the cumulative approved preemption hours this period
        plus the new request's hours must not exceed ten percent of the
        agreement's `clearance_obligation_hours`".

        Design: Corner/validations/preemption_quota_boundary_exactly_10_percent
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-10T00:00:00Z", clearance_obligation_hours=100,
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid, avail_minutes_total=10, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # PR1 = exactly 10 hours = exactly 10% of 100 hours.
        pr1 = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T00:00:00Z",
            requested_end_utc="2026-06-01T10:00:00Z",
        )
        resp1 = _approve(nid, sid, pr1["id"], nar)
        data1 = validate_success(resp1, expected_status=200)
        assert data1["status"] == "APPROVED", (
            f"Exactly 10% of obligation must be allowed; got {data1['status']!r}"
        )

    def test_quota_one_minute_over_rejected(self, api):
        """PRD §3.3: "otherwise the approval is rejected with
        `ERR_PREEMPTION_QUOTA_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/preemption_quota_boundary_exactly_10_percent
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-10T00:00:00Z", clearance_obligation_hours=100,
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid, avail_minutes_total=10, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # Approved PR1: 10h (the full quota).
        pr1 = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T00:00:00Z",
            requested_end_utc="2026-06-01T10:00:00Z",
        )
        validate_success(_approve(nid, sid, pr1["id"], nar), expected_status=200)
        # PR2: 1 minute over.
        pr2 = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-02T00:00:00Z",
            requested_end_utc="2026-06-02T00:01:00Z",
            reason="OTHER",
        )
        resp = _approve(nid, sid, pr2["id"], nar)
        validate_error(resp, ApiErrorId.ERR_PREEMPTION_QUOTA_EXCEEDED)


class TestLockdownBeatsQuota:
    def test_lockdown_blocks_even_under_quota_approval(self, api):
        """PRD §3.3: "the network must not be in `SWEEP_LOCKDOWN` (otherwise
        `ERR_NETWORK_LOCKDOWN`, HTTP 409)" — the lockdown check fires even
        when the request would NOT have exceeded the quota.

        Design: Difficulty/priority_pair_validation_conflict/lockdown_state_beat_quota_fiscal
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-10T00:00:00Z", clearance_obligation_hours=100,
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        drive_network_into_sweep_lockdown(nid, sid, sgo, nar)
        program = create_program(
            nid, avail_minutes_total=20, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # 1-hour preemption — well under the 10-hour quota.
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T00:00:00Z",
            requested_end_utc="2026-06-01T01:00:00Z",
        )
        get_success_data(
            api_client.begin_review_preemption(nid, sid, pr["id"], nar)
        )
        resp = api_client.approve_preemption(nid, sid, pr["id"], nar)
        validate_error(resp, ApiErrorId.ERR_NETWORK_LOCKDOWN)

    def test_lockdown_error_wins_over_quota_error(self, api):
        """PRD §3.3: "Approval moves the request from `UNDER_REVIEW` to
        `APPROVED` and is gated by two checks evaluated in the order given in
        §2.10: first, the network must not be in `SWEEP_LOCKDOWN` (otherwise
        `ERR_NETWORK_LOCKDOWN`, HTTP 409); second, the cumulative approved
        preemption hours this period plus the new request's hours must not
        exceed ten percent of the agreement's `clearance_obligation_hours` —
        otherwise the approval is rejected with
        `ERR_PREEMPTION_QUOTA_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/lockdown_state_beat_quota_fiscal
        """
        scenario = setup_basic_scenario(
            clock_iso="2026-05-10T00:00:00Z", clearance_obligation_hours=100,
        )
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # Drive network into SWEEP_LOCKDOWN.
        drive_network_into_sweep_lockdown(nid, sid, sgo, nar)
        # Verify the network posture flipped.
        net_after = validate_success(api_client.get_network(nid, nar))
        assert net_after["posture"] == "SWEEP_LOCKDOWN", (
            f"3 FAILED compliance reports must drive SWEEP_LOCKDOWN; got "
            f"{net_after['posture']!r}"
        )
        program = create_program(
            nid, avail_minutes_total=20, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # Preemption for 11 hours (would exceed the 10% quota = 10 hours).
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T00:00:00Z",
            requested_end_utc="2026-06-01T11:00:00Z",
        )
        get_success_data(
            api_client.begin_review_preemption(nid, sid, pr["id"], nar)
        )
        resp = api_client.approve_preemption(nid, sid, pr["id"], nar)
        # Both lockdown (priority 5) and quota (priority 12) apply; §2.10
        # states lockdown is evaluated first.
        validate_error(resp, ApiErrorId.ERR_NETWORK_LOCKDOWN)
