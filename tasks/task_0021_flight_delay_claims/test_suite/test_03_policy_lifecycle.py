"""Policy creation, suspend/terminate, risk_view (PRD §3.1, §2.8)."""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    PolicyStatus,
    create_insurer,
    create_policy,
    create_policy_payload,
    setup_basic_insurer_with_policy,
    setup_claim_under_review,
    setup_claim_approved,
    get_policy,
    get_risk_view,
    suspend_policy_payload,
    assert_policy,
    assert_pessimistic_ge_optimistic,
)


class TestPolicyCreation:
    def test_create_policy_starts_active_with_zero_balances(self, api, policy_admin_headers):
        """PRD §3.1: "A new policy starts with status set to ACTIVE and with
        claim_quota_used_cents and reserve_balance_cents initialised to zero."

        Claim: POST /policies returns ACTIVE with zero used quota and zero
        reserve.
        """
        insurer = create_insurer()
        resp = api.create_policy(
            insurer["id"],
            create_policy_payload(),
            policy_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_policy(data)
        assert data["status"] == PolicyStatus.ACTIVE.value
        assert data["claim_quota_used_cents"] == 0
        assert data["reserve_balance_cents"] == 0

    def test_effective_to_must_exceed_effective_from(self, api, policy_admin_headers):
        """PRD §3.1: "the exclusive coverage end effective_to_epoch_ms (which
        must be strictly greater than effective_from_epoch_ms)".

        Claim: effective_to <= effective_from yields ERR_INVALID_REQUEST.
        """
        insurer = create_insurer()
        resp = api.create_policy(
            insurer["id"],
            create_policy_payload(
                effective_from_epoch_ms=1000,
                effective_to_epoch_ms=1000,
            ),
            policy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestSuspendTerminate:
    def test_suspend_blocks_approve(self, api, policy_admin_headers):
        """PRD §3.1: "A PolicyAdmin can suspend the policy (transitioning
        status to SUSPENDED, supplying a reason in the request body) so that
        no new claim approvals are admitted ... When an approval attempt
        finds the parent policy in SUSPENDED or TERMINATED, the request is
        rejected with ERR_POLICY_INACTIVE (HTTP 409)."

        Claim: suspending the parent policy and then approving an
        UNDER_REVIEW claim → ERR_POLICY_INACTIVE.
        """
        insurer, policy, flight, ticket, claim_uw, reviewer_id = setup_claim_under_review()
        suspend_resp = api.suspend_policy(
            insurer["id"], policy["id"],
            suspend_policy_payload(reason="audit"),
            policy_admin_headers,
        )
        suspended = validate_success(suspend_resp)
        assert suspended["status"] == PolicyStatus.SUSPENDED.value
        # Now try to approve the claim — must fail with ERR_POLICY_INACTIVE.
        from test_helpers import (
            make_claims_approver_headers,
            approve_claim_payload,
            fresh_operator_id,
        )
        aid = fresh_operator_id("apr")
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=aid),
            make_claims_approver_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_INACTIVE.value)

    def test_terminate_blocks_approve(self, api, policy_admin_headers):
        """PRD §3.1: "When an approval attempt finds the parent policy in
        SUSPENDED or TERMINATED, the request is rejected with
        ERR_POLICY_INACTIVE (HTTP 409)."

        Claim: terminating the parent policy and then approving →
        ERR_POLICY_INACTIVE.
        """
        insurer, policy, flight, ticket, claim_uw, reviewer_id = setup_claim_under_review()
        resp = api.terminate_policy(
            insurer["id"], policy["id"], policy_admin_headers
        )
        terminated = validate_success(resp)
        assert terminated["status"] == PolicyStatus.TERMINATED.value
        from test_helpers import (
            make_claims_approver_headers,
            approve_claim_payload,
            fresh_operator_id,
        )
        aid = fresh_operator_id("apr")
        resp = api.approve_claim(
            insurer["id"], claim_uw["id"],
            approve_claim_payload(assigned_approver_id=aid),
            make_claims_approver_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_INACTIVE.value)


class TestRiskView:
    def test_risk_view_with_no_claims_zero_reserve(self, api, policy_admin_headers):
        """PRD §3.1: "The pessimistic risk view is a read-only computation
        over a single policy: it returns three values — the
        optimistic_reserve_cents (matching the stored reserve_balance_cents),
        the pessimistic_reserve_cents (the variant that also counts
        UNDER_REVIEW claims as exposure), and the
        claim_quota_remaining_cents (the difference between
        claim_quota_total_cents and claim_quota_used_cents)."

        Claim: a brand-new policy returns zero optimistic, zero pessimistic,
        and full quota_remaining.
        """
        insurer, policy = setup_basic_insurer_with_policy()
        rv = get_risk_view(insurer["id"], policy["id"])
        assert rv["optimistic_reserve_cents"] == 0
        assert rv["pessimistic_reserve_cents"] == 0
        assert rv["claim_quota_remaining_cents"] == policy["claim_quota_total_cents"]

    def test_risk_view_pessimistic_at_least_optimistic(self, api):
        """PRD §2.8: "Whenever a policy has at least one UNDER_REVIEW claim
        with a computed gross payout, the pessimistic figure exceeds the
        optimistic figure; when every in-flight claim is already APPROVED,
        the two are equal."

        Claim: pessimistic_reserve_cents >= optimistic_reserve_cents holds
        unconditionally for any policy state.
        """
        insurer, policy, flight, ticket, claim_uw, _rid = setup_claim_under_review()
        rv = get_risk_view(insurer["id"], policy["id"])
        assert_pessimistic_ge_optimistic(rv)
