"""Concurrency / race conditions — PRD §3.9 (and §3.4, §3.7).

Four serialization points are named in PRD §3.9 with specific error_ids
for the loser:

1. Two DockMasters approving overlapping reservations on the same slip
   → loser receives ERR_SLIP_OCCUPIED.
2. Two simultaneous liveaboard approvals exceeding quota → loser
   receives ERR_LIVEABOARD_QUOTA_EXCEEDED.
3. Accept transfer while DockMaster patches slip to MAINTENANCE → loser
   receives ERR_INVALID_STATE.
4. PATCH/PUT with stale If-Match → ERR_VERSION_CONFLICT.

Concurrent waitlist creations both succeed and each receives a distinct
sequence_no.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_waitlist_entry,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_active_policy,
    create_boater_with_vessel,
    create_marina,
    create_reservation,
    create_slip,
    create_waitlist_payload,
    make_boater_headers,
    run_race,
    setup_quota_full_marina_with_overlap_attempt,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
)


# ===========================================================================
# Concurrent waitlist creation — PRD §3.7, §3.9
# ===========================================================================
class TestConcurrentWaitlistCreation:

    def test_both_succeed_with_distinct_sequence_nos(
        self, api, dock_master_headers,
    ):
        """PRD §3.9: "concurrent waitlist creations both succeed and
        each receives a distinct `sequence_no` from the marina-scoped
        counter."

        Claim: two simultaneous waitlist creations both return 201 with
        distinct sequence_nos."""
        marina = create_marina()
        boater_a, vessel_a = create_boater_with_vessel(marina["id"])
        boater_b, vessel_b = create_boater_with_vessel(marina["id"])

        def _create_a():
            return api_client.create_waitlist_entry(
                marina["id"],
                create_waitlist_payload(
                    boater_id=boater_a["id"], vessel_id=vessel_a["id"],
                    requested_check_in="2024-05-01T00:00:00.000Z",
                    requested_check_out="2024-05-05T00:00:00.000Z",
                ),
                make_boater_headers(boater_a["id"]),
            )

        def _create_b():
            return api_client.create_waitlist_entry(
                marina["id"],
                create_waitlist_payload(
                    boater_id=boater_b["id"], vessel_id=vessel_b["id"],
                    requested_check_in="2024-05-01T00:00:00.000Z",
                    requested_check_out="2024-05-05T00:00:00.000Z",
                ),
                make_boater_headers(boater_b["id"]),
            )

        results = run_race(_create_a, _create_b)
        outcome = assert_race_outcome(results, expected_successes=2,
                                      expected_failures=0)
        seqs = sorted(
            r.json()["data"]["sequence_no"] for r in outcome["successes"]
        )
        assert seqs[0] != seqs[1], (
            f"Both succeed but sequence_nos must differ, got {seqs}"
        )


# ===========================================================================
# Concurrent overlapping approvals — PRD §3.4, §3.9
# ===========================================================================
class TestConcurrentOverlappingApprovals:

    def test_two_overlapping_approvals_one_wins(
        self, api, dock_master_headers,
    ):
        """PRD §3.9: "Two `DockMaster` callers racing to approve
        overlapping reservations on the same slip serialize
        first-writer-wins on the `DRAFT → APPROVED` transition; the
        loser receives `ERR_SLIP_OCCUPIED`."

        Claim: exactly one approval succeeds and the loser receives
        ERR_SLIP_OCCUPIED."""
        marina = create_marina(base_daily_rate_cents=500)
        slip = create_slip(
            marina["id"], code="A-01",
            length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
            flat_daily_charge_cents=2000,
        )
        boater_a, vessel_a = create_boater_with_vessel(marina["id"])
        boater_b, vessel_b = create_boater_with_vessel(marina["id"])
        policy_a = create_active_policy(
            marina["id"], boater_a,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2025-01-01T00:00:00.000Z",
        )
        policy_b = create_active_policy(
            marina["id"], boater_b,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2025-01-01T00:00:00.000Z",
        )
        res_a = create_reservation(
            marina["id"], boater_a, vessel_a, slip, policy_a,
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-10T00:00:00.000Z",
        )
        res_b = create_reservation(
            marina["id"], boater_b, vessel_b, slip, policy_b,
            # overlapping window
            check_in_date="2024-05-05T00:00:00.000Z",
            check_out_date="2024-05-15T00:00:00.000Z",
        )

        def _approve_a():
            return api_client.approve_reservation(
                marina["id"], res_a["id"], dock_master_headers,
            )

        def _approve_b():
            return api_client.approve_reservation(
                marina["id"], res_b["id"], dock_master_headers,
            )

        results = run_race(_approve_a, _approve_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD §3.9 pins the loser's error_id for this race.
        body = loser.json()
        assert body["data"]["error_id"] == "ERR_SLIP_OCCUPIED", (
            f"Loser of overlapping-approval race must receive "
            f"ERR_SLIP_OCCUPIED, got {body['data']['error_id']!r}"
        )


# ===========================================================================
# Concurrent liveaboard quota race — PRD §3.4, §3.9
# ===========================================================================
class TestConcurrentLiveaboardQuota:

    def test_quota_one_two_approvals_one_wins(
        self, api, dock_master_headers,
    ):
        """PRD §3.9: "Two simultaneous liveaboard approvals where the
        marina would exceed `liveaboard_quota` serialize
        first-writer-wins on the `liveaboard_active_count` increment;
        the loser receives `ERR_LIVEABOARD_QUOTA_EXCEEDED`."

        Setup: liveaboard_quota=1, two DRAFT liveaboard reservations on
        DIFFERENT slips (so the overlap rule doesn't fire) with
        non-overlapping date windows that nevertheless both want to
        increment the active count.

        Claim: exactly one approval succeeds; loser gets
        ERR_LIVEABOARD_QUOTA_EXCEEDED."""
        marina = create_marina(
            base_daily_rate_cents=500, liveaboard_quota=1,
        )
        slip_a = create_slip(
            marina["id"], code="A-01",
            length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
            flat_daily_charge_cents=2000,
            liveaboard_allowed=True,
        )
        slip_b = create_slip(
            marina["id"], code="B-01",
            length_feet=40.0, beam_feet=14.0, depth_feet=6.0,
            flat_daily_charge_cents=2000,
            liveaboard_allowed=True,
        )
        boater_a, vessel_a = create_boater_with_vessel(
            marina["id"],
            loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
            holding_tank_gallons=40,
        )
        boater_b, vessel_b = create_boater_with_vessel(
            marina["id"],
            loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
            holding_tank_gallons=40,
        )
        policy_a = create_active_policy(
            marina["id"], boater_a,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2025-01-01T00:00:00.000Z",
        )
        policy_b = create_active_policy(
            marina["id"], boater_b,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2025-01-01T00:00:00.000Z",
        )
        res_a = create_reservation(
            marina["id"], boater_a, vessel_a, slip_a, policy_a,
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=True,
        )
        res_b = create_reservation(
            marina["id"], boater_b, vessel_b, slip_b, policy_b,
            check_in_date="2024-06-01T00:00:00.000Z",
            check_out_date="2024-06-05T00:00:00.000Z",
            liveaboard=True,
        )

        def _approve_a():
            return api_client.approve_reservation(
                marina["id"], res_a["id"], dock_master_headers,
            )

        def _approve_b():
            return api_client.approve_reservation(
                marina["id"], res_b["id"], dock_master_headers,
            )

        results = run_race(_approve_a, _approve_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        # PRD §3.9 pins the loser's error_id for this race.
        assert (
            body["data"]["error_id"] == "ERR_LIVEABOARD_QUOTA_EXCEEDED"
        ), (
            "Loser of liveaboard-quota race must receive "
            f"ERR_LIVEABOARD_QUOTA_EXCEEDED, got "
            f"{body['data']['error_id']!r}"
        )
