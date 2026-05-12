"""Water quotas, parallel state dimensions, override workflow.

PRD references:
  - §3.5 Water Quotas, Carry-Forward, and Over-Quota Approval
  - §2.10 Concurrency: simultaneous approve/reject
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_days,
    add_hours,
    approve_override,
    assert_water_quota,
    create_water_quota,
    create_water_quota_payload,
    DEFAULT_NOW_ISO,
    drive_command_to_executed,
    find_audit_entries,
    get_quota,
    list_audit_logs,
    request_override,
    request_override_payload,
    approve_override_payload,
    setup_full_active_scenario,
    setup_quota_at_usage,
    setup_quota_in_pending_approval,
    setup_tenant_plot_quota,
    suspend_plan,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    run_race,
    assert_exactly_one_succeeds,
    TEST_USERS,
)


# ===========================================================================
# §3.5 — Quota creation
# ===========================================================================
class TestQuotaCreate:
    def test_create_quota_returns_initial_state(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'A WaterAdmin allocates a quota by supplying
        plot_id, period_start, period_end, a non-negative
        allocated_liters, and an optional warning_threshold_pct whose
        default is 80 and which must be at least 1 and at most 100.'

        Claim: quota begins UNDER usage, NOT_REQUIRED approval, default
        warning threshold 80, and zero approval_extra_liters.
        """
        from test_helpers import create_plot, create_tenant
        tenant = create_tenant()
        plot = create_plot(tenant["id"])
        res = api.create_water_quota(
            create_water_quota_payload(
                plot_id=plot["id"],
                period_start=DEFAULT_NOW_ISO,
                period_end=add_days(DEFAULT_NOW_ISO, 30),
                allocated_liters=10000.0,
            ),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_water_quota(data)
        assert data["usage_state"] == "UNDER"
        assert data["approval_state"] == "NOT_REQUIRED"
        assert data["warning_threshold_pct"] == 80
        assert data["approval_extra_liters"] == 0

    @pytest.mark.parametrize("bad_pct", [0, -5, 101, 150])
    def test_warning_threshold_out_of_range_rejected(
        self, api, water_admin_headers, bad_pct,
    ):
        """PRD §3.5: 'an optional warning_threshold_pct whose default
        is 80 and which must be at least 1 and at most 100.'

        Claim: warning_threshold_pct outside [1, 100] should be
        rejected (ERR_VALIDATION on body shape).
        """
        from test_helpers import create_plot, create_tenant
        tenant = create_tenant()
        plot = create_plot(tenant["id"])
        res = api.create_water_quota(
            create_water_quota_payload(
                plot_id=plot["id"],
                period_start=DEFAULT_NOW_ISO,
                period_end=add_days(DEFAULT_NOW_ISO, 30),
                allocated_liters=10000.0,
                warning_threshold_pct=bad_pct,
            ),
            water_admin_headers,
        )
        # PRD doesn't pin which error_id the validator emits, but the
        # constraint is named in §3.5 and must reject. Use validate
        # against expected catalog membership.
        body = res.json()
        assert res.status_code in (400, 422), (
            f"Expected 4xx for warning_threshold_pct={bad_pct}, got "
            f"{res.status_code}"
        )
        assert body["data"]["error_id"] in (
            "ERR_VALIDATION",
        ), (
            "PRD §3.5 caps warning_threshold_pct in [1, 100]; PRD §2.9 "
            "routes generic body validation through ERR_VALIDATION."
        )

    def test_quota_create_appends_quota_allocated_audit(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'A QUOTA_ALLOCATED AuditLog entry is appended.'

        Claim: an AuditLog with action_type==QUOTA_ALLOCATED exists
        for the new quota.
        """
        from test_helpers import create_plot, create_tenant
        tenant = create_tenant()
        plot = create_plot(tenant["id"])
        res = api.create_water_quota(
            create_water_quota_payload(
                plot_id=plot["id"],
                period_start=DEFAULT_NOW_ISO,
                period_end=add_days(DEFAULT_NOW_ISO, 30),
                allocated_liters=10000.0,
            ),
            water_admin_headers,
        )
        quota = validate_success(res, expected_status=201)
        entries = list_audit_logs(
            params={"action_type": "QUOTA_ALLOCATED", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="QUOTA_ALLOCATED", subject_id=quota["id"]
        )
        assert len(matched) >= 1


# ===========================================================================
# §3.5 — usage_state thresholds: warning_threshold inclusive lower bound
# ===========================================================================
class TestUsageStateThresholds:
    def test_under_below_warning_threshold(self, api):
        """PRD §3.5: 'otherwise, if the ratio of final_used_liters to
        effective_allocation is at least warning_threshold_pct divided
        by 100, the state is WARNING; otherwise the state is UNDER.'

        Claim: 79.99% < 80% → UNDER.
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=7999.99,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        quota = ctx["quota_after"]
        assert quota["final_used_liters"] == pytest.approx(7999.99, abs=0.01)
        assert quota["usage_state"] == "UNDER"

    def test_warning_at_inclusive_threshold(self, api):
        """PRD §3.5: 'if the ratio of final_used_liters to
        effective_allocation is at least warning_threshold_pct divided
        by 100, the state is WARNING'.

        Claim: ratio == warning_threshold_pct/100 (8000/10000 = 0.80,
        threshold=80) → WARNING (inclusive lower bound).
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=8000.0,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        quota = ctx["quota_after"]
        assert quota["final_used_liters"] == pytest.approx(8000.0, abs=0.01)
        assert quota["usage_state"] == "WARNING"

    def test_over_when_final_exceeds_effective(self, api):
        """PRD §3.5: 'If final_used_liters is at least equal to
        effective_allocation the state is OVER'.

        Claim: 10500 > 10000 → OVER.
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=10500.0,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        quota = ctx["quota_after"]
        assert quota["final_used_liters"] == pytest.approx(10500.0, abs=0.01)
        assert quota["usage_state"] == "OVER"


# ===========================================================================
# §3.5 — Override workflow: parallel approval_state dimension
# ===========================================================================
class TestOverrideWorkflow:
    def test_request_override_requires_over(
        self, api, operator_headers,
    ):
        """PRD §3.5: 'An Operator may post an override request
        (supplying a free-text reason) when usage_state is OVER and
        approval_state is NOT_REQUIRED; this advances approval_state
        from NOT_REQUIRED to PENDING_APPROVAL.'

        Claim: request-override on UNDER quota → ERR_INVALID_STATE
        (state precondition fails).
        """
        ctx = setup_full_active_scenario(plan_volume_liters=100.0)
        # Quota is UNDER — request-override must reject.
        res = api.request_quota_override(
            ctx["quota"]["id"],
            request_override_payload(reason="anything"),
            operator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_request_override_advances_to_pending_approval(self, api):
        """PRD §3.5: 'this advances approval_state from NOT_REQUIRED
        to PENDING_APPROVAL.'

        Claim: with usage_state=OVER, request-override flips
        approval_state → PENDING_APPROVAL.
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=11000.0,
            allocated_liters=10000.0,
        )
        quota = ctx["quota_after"]
        assert quota["usage_state"] == "OVER"
        result = request_override(quota["id"], reason="urgent")
        assert result["approval_state"] == "PENDING_APPROVAL"

    @pytest.mark.parametrize("bad_extra", [0, -1, 5001, 10000])
    def test_approve_extra_liters_out_of_range_rejected(
        self, api, water_admin_headers, bad_extra,
    ):
        """PRD §3.5: 'Approval requires the request body to specify an
        extra_liters value strictly greater than zero and at most
        fifty percent of allocated_liters; an out-of-range extra_liters
        is rejected with ERR_OVERRIDE_AMOUNT_INVALID (422).'

        Claim: extra_liters in {0, negative, > 50% allocated} →
        ERR_OVERRIDE_AMOUNT_INVALID. (allocated=10000 → cap is 5000)
        """
        ctx = setup_quota_in_pending_approval(
            allocated_liters=10000.0, warning_threshold_pct=80,
        )
        quota = ctx["quota"]
        res = api.approve_quota_override(
            quota["id"],
            approve_override_payload(extra_liters=bad_extra),
            water_admin_headers,
        )
        validate_error(res, "ERR_OVERRIDE_AMOUNT_INVALID")

    @pytest.mark.parametrize("good_extra", [1, 2500, 5000])
    def test_approve_extra_liters_in_range_accepted(
        self, api, water_admin_headers, good_extra,
    ):
        """PRD §3.5: 'Approval requires the request body to specify an
        extra_liters value strictly greater than zero and at most
        fifty percent of allocated_liters'.

        Claim: extra_liters in (0, 5000] (50% of 10000) is accepted
        and quota.approval_state advances to APPROVED.
        """
        ctx = setup_quota_in_pending_approval(
            allocated_liters=10000.0, warning_threshold_pct=80,
        )
        quota = ctx["quota"]
        res = api.approve_quota_override(
            quota["id"],
            approve_override_payload(extra_liters=good_extra),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["approval_state"] == "APPROVED"
        assert data["approval_extra_liters"] == pytest.approx(
            good_extra, abs=0.01
        )

    def test_approve_override_appends_audit(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'On approval the system sets approval_extra_liters
        to the supplied extra_liters, recomputes effective_allocation
        and usage_state ..., and appends a QUOTA_OVERRIDE_APPROVED
        AuditLog entry.'

        Claim: AuditLog with action_type==QUOTA_OVERRIDE_APPROVED.
        """
        ctx = setup_quota_in_pending_approval(
            allocated_liters=10000.0,
        )
        approve_override(ctx["quota"]["id"], extra_liters=2000.0)
        entries = list_audit_logs(
            params={"action_type": "QUOTA_OVERRIDE_APPROVED", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="QUOTA_OVERRIDE_APPROVED",
            subject_id=ctx["quota"]["id"],
        )
        assert len(matched) >= 1

    def test_reject_override_appends_audit(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'Rejection accepts an optional reason, advances
        approval_state to REJECTED, and appends a
        QUOTA_OVERRIDE_REJECTED AuditLog entry.'

        Claim: AuditLog with action_type==QUOTA_OVERRIDE_REJECTED.
        """
        ctx = setup_quota_in_pending_approval(
            allocated_liters=10000.0,
        )
        res = api.reject_quota_override(
            ctx["quota"]["id"], {"reason": "no"}, water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["approval_state"] == "REJECTED"
        entries = list_audit_logs(
            params={"action_type": "QUOTA_OVERRIDE_REJECTED", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="QUOTA_OVERRIDE_REJECTED",
            subject_id=ctx["quota"]["id"],
        )
        assert len(matched) >= 1

    def test_decide_when_not_pending_returns_invalid_state(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'An attempt to decide a request that is not in
        PENDING_APPROVAL returns ERR_INVALID_STATE (409).'

        Claim: approve on a quota with approval_state=NOT_REQUIRED →
        ERR_INVALID_STATE.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=100.0)
        # quota.approval_state is NOT_REQUIRED here.
        res = api.approve_quota_override(
            ctx["quota"]["id"],
            approve_override_payload(extra_liters=1000.0),
            water_admin_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_concurrent_approve_and_reject_exactly_one_wins(self, api):
        """PRD §2.10: 'When a WaterAdmin simultaneously approves and
        rejects the same quota override request, the system serialises
        on the approval_state transition out of PENDING_APPROVAL;
        whichever decision lands first wins, and the loser receives
        ERR_OVERRIDE_ALREADY_DECIDED with HTTP 409.'

        Claim: simultaneous approve+reject on PENDING_APPROVAL → exactly
        one succeeds.
        """
        ctx = setup_quota_in_pending_approval(allocated_liters=10000.0)
        quota_id = ctx["quota"]["id"]
        results = run_race(
            lambda: api.approve_quota_override(
                quota_id,
                approve_override_payload(extra_liters=2000.0),
                TEST_USERS["water_admin_headers"],
            ),
            lambda: api.reject_quota_override(
                quota_id, {"reason": "no"},
                TEST_USERS["water_admin_headers_alt"],
            ),
        )
        assert_exactly_one_succeeds(*results)


# ===========================================================================
# §3.5 — Quota guard at command creation (ERR_QUOTA_EXCEEDED)
# ===========================================================================
class TestQuotaGuardOnCommandCreate:
    def test_quota_exceeded_blocks_command_creation(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'The quota guard then evaluates whether reserving
        the new command's requested_volume_liters against
        WaterQuota.provisional_used_liters would push the covering
        quota's usage_state to OVER; if it would and the quota's
        approval_state is anything other than APPROVED, the creation
        is rejected with ERR_QUOTA_EXCEEDED (422).'

        Claim: requested_volume_liters that would push to OVER without
        APPROVED → ERR_QUOTA_EXCEEDED.
        """
        ctx = setup_full_active_scenario(
            allocated_liters=1000.0, plan_volume_liters=1.0,
        )
        # Try to create a command requesting much more than allocated.
        res = api.create_control_command(
            {
                "plan_id": ctx["plan"]["id"],
                "valve_group_id": ctx["valve_group"]["id"],
                "requested_volume_liters": 999_999.0,
            },
            water_admin_headers,
        )
        validate_error(res, "ERR_QUOTA_EXCEEDED")
