"""Difficulty Rule 8 — resource_temporal_overlap.

Instance A (slip_lease_half_open_overlap_rejects_strict_intersect) is SKIPPED:
PRD §3.4 fires the slip-state check (ERR_INVALID_STATE) before the date
conflict check; a slip in RESERVED state from an existing lease will reject
any subsequent /leases POST with ERR_INVALID_STATE rather than
ERR_SLIP_DATE_CONFLICT. A faithful PRD-only implementer thus has no path
to surface the date-conflict error_id on the same slip — the test's asserted
error_id is not uniquely derivable.

Instance B (liveaboard_quota_aggregate_capacity_at_marina) — aggregate
capacity at marina returns ERR_LIVEABOARD_QUOTA_EXCEEDED at saturation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_marina,
    create_tenant,
    apply_liveaboard,
    approve_liveaboard,
    ApiErrorId,
    TEST_USERS,
)


class TestLiveaboardQuotaAggregateCapacityAtMarina:
    """Marina.liveaboard_cap == 2; two tenants already APPROVED; third
    PENDING approval is REJECTED with ERR_LIVEABOARD_QUOTA_EXCEEDED.
    """

    def _saturated_marina(self):
        marina = create_marina(liveaboard_cap=2)
        tj = create_tenant(full_name="T J")
        tk = create_tenant(full_name="T K")
        tl = create_tenant(full_name="T L")
        apply_liveaboard(tj["id"], marina["id"])
        approve_liveaboard(tj["id"], marina["id"])
        apply_liveaboard(tk["id"], marina["id"])
        approve_liveaboard(tk["id"], marina["id"])
        apply_liveaboard(tl["id"], marina["id"])
        return marina, tl

    def test_third_approval_at_saturation_returns_quota_exceeded(self, api):
        """PRD §3.3: "Approval is gated by the liveaboard quota: if the marina's current count is greater than or equal to its cap, approval is rejected with `ERR_LIVEABOARD_QUOTA_EXCEEDED` and HTTP 409."

        Design: Difficulty/resource_temporal_overlap/liveaboard_quota_aggregate_capacity_at_marina
        """
        marina, tl = self._saturated_marina()
        res = api.approve_liveaboard(
            tl["id"], {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        validate_error(res, ApiErrorId.ERR_LIVEABOARD_QUOTA_EXCEEDED)

    def test_marina_count_stays_at_cap_after_saturated_rejection(self, api):
        """PRD §3.1: "On creation the marina's `liveaboard_current_count` is initialised to zero and tracks the live count of tenants whose `liveaboard_status` is `APPROVED` and whose active lease's `marina_id` equals this marina; the field is recomputed on every tenant liveaboard transition and on every lease check-in or check-out."

        Design: Difficulty/resource_temporal_overlap/liveaboard_quota_aggregate_capacity_at_marina
        """
        marina, tl = self._saturated_marina()
        api.approve_liveaboard(
            tl["id"], {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        res = api.get_marina(marina["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["liveaboard_current_count"] == 2, \
            f"count must remain at cap=2 after saturated rejection, got {data['liveaboard_current_count']}"
