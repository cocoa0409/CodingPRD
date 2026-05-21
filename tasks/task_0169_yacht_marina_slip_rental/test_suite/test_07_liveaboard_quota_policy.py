"""Liveaboard policy and quota enforcement — PRD §3.4, §2.10.

Liveaboard reservations require:
- Slip.liveaboard_allowed == true
- Vessel.holding_tank_gallons != null
- Marina.liveaboard_active_count < Marina.liveaboard_quota

When the quota is exceeded an approval is rejected with
ERR_LIVEABOARD_QUOTA_EXCEEDED. When the policy preconditions fail
(slip not liveaboard, or no holding tank) the rejection is
ERR_LIVEABOARD_POLICY_VIOLATION. The active count is then maintained
as a derived counter (PRD §2.10).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    approve_reservation,
    advance_clock_to_iso,
    assert_liveaboard_count_matches,
    cancel_reservation_as_boater,
    check_in_reservation,
    check_out_reservation,
    create_active_policy,
    create_boater_with_vessel,
    create_marina,
    create_reservation,
    create_slip,
    get_marina,
    setup_draft_reservation,
    setup_approved_reservation,
    setup_quota_full_marina_with_overlap_attempt,
    validate_error,
)


# ===========================================================================
# Liveaboard policy violation — PRD §3.4
# ===========================================================================
class TestLiveaboardPolicy:

    def test_liveaboard_on_non_liveaboard_slip_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "A liveaboard reservation against a slip that
        does not permit liveaboard occupancy ... is rejected with
        `ERR_LIVEABOARD_POLICY_VIOLATION`."

        Claim: liveaboard=true on a slip whose liveaboard_allowed=false
        → ERR_LIVEABOARD_POLICY_VIOLATION."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=False,
            vessel_holding_tank_gallons=40,
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_LIVEABOARD_POLICY_VIOLATION.value,
        )

    def test_liveaboard_without_holding_tank_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "...against a vessel with no holding tank capacity
        recorded, is rejected with `ERR_LIVEABOARD_POLICY_VIOLATION`."

        Claim: liveaboard=true on a vessel without holding_tank_gallons
        → ERR_LIVEABOARD_POLICY_VIOLATION."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=None,  # omitted
        )
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            dock_master_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_LIVEABOARD_POLICY_VIOLATION.value,
        )


# ===========================================================================
# Liveaboard quota — PRD §3.4
# ===========================================================================
class TestLiveaboardQuota:

    def test_quota_exceeded_rejects_approval(
        self, api, dock_master_headers,
    ):
        """PRD §3.4: "a liveaboard reservation that would push the
        marina to or beyond its quota is rejected with
        `ERR_LIVEABOARD_QUOTA_EXCEEDED`."

        Claim: a second liveaboard approval that would push the count
        beyond the quota fails with ERR_LIVEABOARD_QUOTA_EXCEEDED."""
        # Quota=1, one approved liveaboard already.
        scenario = setup_quota_full_marina_with_overlap_attempt(quota=1)
        resp = api.approve_reservation(
            scenario["marina"]["id"], scenario["res_new"]["id"],
            dock_master_headers,
        )
        # Per PRD §3.4 priority order (priority 10 quota fires BEFORE
        # priority 11 overlap), the quota error wins here.
        validate_error(
            resp, ApiErrorId.ERR_LIVEABOARD_QUOTA_EXCEEDED.value,
        )


# ===========================================================================
# liveaboard_active_count derived counter — PRD §2.10
# ===========================================================================
class TestLiveaboardCountDerivation:

    def test_count_increments_on_approve(
        self, api, dock_master_headers,
    ):
        """PRD §2.10: "It is maintained in lock-step with the
        reservation state machine — incremented on a liveaboard
        transition into `APPROVED`..."

        Claim: Marina.liveaboard_active_count == 1 after approving a
        liveaboard reservation, starting from 0."""
        scenario = setup_draft_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=40,
            liveaboard_quota=3,
        )
        # Before approval the count is 0.
        marina_before = get_marina(scenario["marina"]["id"])
        assert marina_before["liveaboard_active_count"] == 0
        # Approve and re-read marina.
        approve_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        marina_after = get_marina(scenario["marina"]["id"])
        assert_liveaboard_count_matches(marina_after, 1)

    def test_count_decrements_on_cancel_from_approved(
        self, api, dock_master_headers,
    ):
        """PRD §2.10: "decremented when a liveaboard reservation
        leaves `APPROVED` for `CANCELLED` or `EXPIRED`..."

        Claim: count drops back to 0 when the only APPROVED liveaboard
        reservation is cancelled."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=40,
            liveaboard_quota=3,
        )
        marina_after_approve = get_marina(scenario["marina"]["id"])
        assert marina_after_approve["liveaboard_active_count"] == 1
        # Cancel from APPROVED.
        cancel_reservation_as_boater(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
        )
        marina_after_cancel = get_marina(scenario["marina"]["id"])
        assert_liveaboard_count_matches(marina_after_cancel, 0)

    def test_count_decrements_on_checked_out(
        self, api, dock_master_headers,
    ):
        """PRD §2.10: "...and decremented again when a liveaboard
        reservation completes `CHECKED_IN → CHECKED_OUT`."

        Claim: count drops to 0 after CHECKED_IN → CHECKED_OUT on the
        only liveaboard."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-03T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=40,
            liveaboard_quota=3,
        )
        marina_id = scenario["marina"]["id"]
        # Walk through check-in then check-out.
        advance_clock_to_iso(marina_id, "2024-05-01T00:00:00.000Z")
        check_in_reservation(marina_id, scenario["reservation"]["id"])
        advance_clock_to_iso(marina_id, "2024-05-03T00:00:00.000Z")
        check_out_reservation(marina_id, scenario["reservation"]["id"])
        marina_after = get_marina(marina_id)
        assert_liveaboard_count_matches(marina_after, 0)
