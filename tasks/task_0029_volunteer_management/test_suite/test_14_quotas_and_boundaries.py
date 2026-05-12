"""Boundary-precision and quota tests on Application approval
(PRD §3.4). Covers difficulty-design rule 6 instance 2 (position_quota
strict less-than) and rule 9 instance 1 (compensating-action invariant
on filled_positions).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    apply_to_activity,
    approve_application,
    create_verified_volunteer,
    get_activity,
    make_organizer_headers,
    make_volunteer_headers,
    setup_recruiting_activity,
    validate_error,
    validate_success,
    withdraw_application,
)


class TestPositionQuotaBoundary:
    """difficulty: boundary_precision_check/position_quota_strict_less_than_on_application_approve"""

    def test_approval_blocked_when_filled_positions_at_quota(self, api):
        """PRD §3.4: 'Approval requires the activity to currently be in
        RECRUITING and Activity.filled_positions to be strictly less
        than Activity.position_quota at the moment of commit ... Quota
        saturation at commit time produces ERR_QUOTA_EXCEEDED.'

        Setup: position_quota=2; two volunteers already approved so
        filled_positions=2; third volunteer applies and is rejected
        with ERR_QUOTA_EXCEEDED.

        # difficulty: boundary_precision_check/position_quota_strict_less_than_on_application_approve
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        # First two approvals fill the quota.
        v1 = create_verified_volunteer()
        v2 = create_verified_volunteer()
        a1 = apply_to_activity(volunteer=v1, activity=activity)
        approve_application(application=a1, organizer=organizer)
        a2 = apply_to_activity(volunteer=v2, activity=activity)
        approve_application(application=a2, organizer=organizer)
        # Verify filled_positions == 2.
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 2

        # Third volunteer applies and Organizer attempts approval.
        v3 = create_verified_volunteer()
        a3 = apply_to_activity(volunteer=v3, activity=activity)
        res = api.approve_application(
            a3["id"], make_organizer_headers(organizer["id"])
        )
        validate_error(res, "ERR_QUOTA_EXCEEDED")
        # filled_positions still 2.
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 2

    def test_approval_succeeds_at_quota_minus_one(self, api):
        """PRD §3.4: '... strictly less than Activity.position_quota at
        the moment of commit.' At quota - 1, the strict-less-than
        predicate holds, so approval succeeds and brings
        filled_positions to quota.
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v1 = create_verified_volunteer()
        a1 = apply_to_activity(volunteer=v1, activity=activity)
        approve_application(application=a1, organizer=organizer)
        # filled_positions == 1, quota == 2 -> strict-less-than holds.
        v2 = create_verified_volunteer()
        a2 = apply_to_activity(volunteer=v2, activity=activity)
        res = api.approve_application(a2["id"], make_organizer_headers(organizer["id"]))
        data = validate_success(res, expected_status=200)
        assert data["status"] == "APPROVED"
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 2


class TestFilledPositionsCompensatingInvariant:
    """difficulty: compensating_invariant/application_withdraw_restores_filled_positions"""

    def test_approve_then_withdraw_restores_filled_positions_to_zero(self, api):
        """PRD §3.4: 'Successful approval ... atomically increments
        Activity.filled_positions by exactly 1.'
        PRD §3.4: 'an APPROVED application may be withdrawn by the
        volunteer only while the parent activity is still RECRUITING,
        and the withdrawal additionally decrements
        Activity.filled_positions by exactly 1 to free the slot.'

        Forward: approve -> filled_positions becomes 1. Compensating:
        withdraw while RECRUITING -> filled_positions becomes 0.

        # difficulty: compensating_invariant/application_withdraw_restores_filled_positions
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=5)
        # Baseline.
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 0

        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=application, organizer=organizer)

        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 1

        # Compensating action: volunteer withdraws while activity still RECRUITING.
        result = withdraw_application(application=application, volunteer=v)
        assert result["status"] == "WITHDRAWN"

        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 0
