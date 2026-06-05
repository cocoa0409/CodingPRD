"""Difficulty Rule 6 — boundary_precision_check.

Instance A — liveaboard quota at the boundary count == cap is REJECTED
            per PRD §3.3's 'greater than or equal to' wording.

Instance B (lease_overlap_adjacent_dates_do_not_collide) is SKIPPED:
PRD §3.4 enforces the slip-AVAILABLE state check before the date-conflict
check. Two RESERVED/ACTIVE leases on the same slip is structurally
impossible (the slip becomes RESERVED at first create), so the half-open
adjacency rule named in PRD has no reachable scenario in which it pins a
unique observable outcome.
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


class TestLiveaboardQuotaStrictLessThan:
    """Marina.liveaboard_cap == 1; first tenant already APPROVED so count == 1
    == cap. Approving second pending tenant must be REJECTED with
    ERR_LIVEABOARD_QUOTA_EXCEEDED.
    """

    def _setup(self):
        marina = create_marina(liveaboard_cap=1)
        tb = create_tenant(full_name="T B")
        tc = create_tenant(full_name="T C")
        apply_liveaboard(tb["id"], marina["id"])
        approve_liveaboard(tb["id"], marina["id"])
        apply_liveaboard(tc["id"], marina["id"])
        return marina, tc

    def test_approval_rejected_when_count_equals_cap(self, api):
        """PRD §3.3: "Approval is gated by the liveaboard quota: if the marina's current count is greater than or equal to its cap, approval is rejected with `ERR_LIVEABOARD_QUOTA_EXCEEDED` and HTTP 409."

        Design: Difficulty/boundary_precision_check/liveaboard_quota_strict_less_than
        """
        marina, tc = self._setup()
        res = api.approve_liveaboard(
            tc["id"], {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        validate_error(res, ApiErrorId.ERR_LIVEABOARD_QUOTA_EXCEEDED)

    def test_liveaboard_count_stays_at_cap_after_rejected_approval(self, api):
        """PRD §3.1: "On creation the marina's `liveaboard_current_count` is initialised to zero and tracks the live count of tenants whose `liveaboard_status` is `APPROVED` and whose active lease's `marina_id` equals this marina; the field is recomputed on every tenant liveaboard transition and on every lease check-in or check-out."

        Design: Difficulty/boundary_precision_check/liveaboard_quota_strict_less_than
        """
        marina, tc = self._setup()
        api.approve_liveaboard(
            tc["id"], {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        res = api.get_marina(marina["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        # Quota rejection means count did NOT increment past cap.
        assert data["liveaboard_current_count"] == 1, \
            f"count must remain at cap=1 after rejection, got {data['liveaboard_current_count']}"
