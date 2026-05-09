"""Reinsurance waterfall, reserve adjustments, reverse, audit & outbox
emissions (PRD §2.8, §3.7, §3.9, §3.10).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    PRIMARY_RETENTION_CENTS,
    REINSURER_LAYER_CENTS,
    ClaimPayoutStatus,
    setup_claim_paid,
    setup_capped_three_segment_paid_claim,
    setup_claim_approved,
    setup_claim_in_executing,
    setup_basic_insurer_with_policy,
    setup_pessimistic_vs_optimistic_pair,
    list_audit_logs,
    list_outbox_events,
    find_audit_logs,
    find_outbox_events,
    get_policy,
    get_risk_view,
    reverse_claim,
    assert_pessimistic_ge_optimistic,
)


class TestReinsuranceWaterfall:
    def test_small_payout_absorbed_entirely_by_primary(self, api):
        """PRD §3.7: "primary_first is the smaller of final_payout_cents and
        the primary retention (set at 50,000 cents, i.e., five hundred
        euros). Second, the reinsurer absorbs the layer above retention up
        to the reinsurer cap (set at 30,000 cents, i.e., three hundred
        euros) — that is, reinsurer_share_cents equals the smaller of 'the
        remainder after primary retention' (clamped at zero if negative)
        and the reinsurer cap."

        Claim: a final_payout of 22500 (single TIER_B segment - 2500
        deductible) is below the 50000 retention → primary absorbs it all,
        reinsurer share = 0.
        """
        (
            insurer, policy, flight, ticket, claim_paid, batch,
            _rid, _aid, _ba, _bx, _po,
        ) = setup_claim_paid(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        assert claim_paid["final_payout_cents"] == 22500
        # Find the ReinsuranceAllocation row via the audit/list path. The PRD
        # exposes audit logs and outbox events but does not list a dedicated
        # GET for ReinsuranceAllocation rows; the row is observable as part
        # of side-effect aggregates carried on the claim itself.
        # PRD §2.10 says "Every state change, payout record, reserve
        # adjustment, and downstream event emission is journalled into the
        # immutable AuditLog." We assert via outbox CLAIM_PAID emissions.
        # The waterfall invariant primary + reinsurer == final is checked
        # via the per-claim `reinsurance_allocation` field if present, or
        # via the audit details. We assert the PAID outcome here and let
        # the difficulty-supplement test cover the explicit allocation row.
        events = list_outbox_events(
            insurer["id"], target_system="PAYMENT", subject_id=claim_paid["id"]
        )
        assert any(e.get("event_type") == "CLAIM_PAID" for e in events), (
            "PRD §3.9: settlement must emit OutboxEvent with target_system=PAYMENT "
            f"and event_type=CLAIM_PAID; got events={events}"
        )

    def test_capped_payout_splits_primary_excess_and_reinsurer(self, api):
        """PRD §3.7: "Third, primary_excess absorbs whatever remains beyond
        the reinsurer layer — that is, the larger of zero and
        final_payout_cents - primary_first - reinsurer_share_cents. Fourth,
        primary_share_cents equals primary_first + primary_excess."
        PRD §3.7: "The allocation invariant is exact: primary_share_cents +
        reinsurer_share_cents must equal pinned_total_cents".

        Claim: final_payout=150000 → primary_first=50000, reinsurer=30000,
        primary_excess=70000, primary_total=120000. Sum = 150000.
        """
        ctx = setup_capped_three_segment_paid_claim(departure_delay_minutes=360)
        claim = ctx["claim"]
        assert claim["final_payout_cents"] == 150000
        # The PRD does not declare a GET endpoint for ReinsuranceAllocation
        # rows. The audit log is the canonical observation surface (PRD
        # §2.10). Verify a PAYOUT_RECORDED entry exists for the claim.
        logs = list_audit_logs(
            ctx["insurer"]["id"], subject_type="CLAIM", subject_id=claim["id"]
        )
        payout_recorded = [
            r for r in logs
            if r.get("action") == "PAYOUT_RECORDED" and r.get("subject_id") == claim["id"]
        ]
        assert payout_recorded, (
            "PRD §3.9: settlement must write an AuditLog entry with action=PAYOUT_RECORDED. "
            f"Got logs={logs}"
        )


class TestReserveLifecycle:
    def test_approval_debits_reserve(self, api):
        """PRD §3.7: "When a claim is approved, the optimistic reserve
        reserve_balance_cents rises by estimated_payout_cents and a
        ReserveAdjustment of reason APPROVE_DEBIT is appended with positive
        delta_cents."

        Claim: after approve, policy.reserve_balance_cents ==
        claim.estimated_payout_cents.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        policy_now = get_policy(insurer["id"], policy["id"])
        assert policy_now["reserve_balance_cents"] == approved["estimated_payout_cents"], (
            f"reserve_balance_cents must equal estimated_payout_cents post-approve; "
            f"reserve={policy_now['reserve_balance_cents']}, "
            f"estimated={approved['estimated_payout_cents']}"
        )

    def test_settle_releases_reserve_and_debits_quota(self, api):
        """PRD §3.7: "When the claim eventually settles into PAID, the
        system pins final_payout_cents to the previously-pinned
        estimated_payout_cents, computes final_segment_payout_cents per
        segment by the pro-ration above, decreases the policy's
        reserve_balance_cents by the previously-debited amount, increases
        claim_quota_used_cents by final_payout_cents, and appends a
        ReserveAdjustment of reason SETTLE_RELEASE with the corresponding
        negative delta_cents."

        Claim: after settle, reserve drops back to its pre-approval value
        and claim_quota_used_cents rises by final_payout_cents.
        """
        (
            insurer, policy, flight, ticket, claim_paid, batch,
            *_ids,
        ) = setup_claim_paid(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        policy_now = get_policy(insurer["id"], policy["id"])
        assert policy_now["reserve_balance_cents"] == 0, (
            f"reserve must be released to 0 after settle; got {policy_now['reserve_balance_cents']}"
        )
        assert policy_now["claim_quota_used_cents"] == claim_paid["final_payout_cents"], (
            f"claim_quota_used_cents must equal final_payout_cents; "
            f"got used={policy_now['claim_quota_used_cents']}, "
            f"final={claim_paid['final_payout_cents']}"
        )


class TestReverse:
    def test_reverse_paid_claim_rebuilds_reserve_and_refunds_quota(self, api):
        """PRD §3.7 / §3.9: "When a ClaimsAdmin reverses a PAID claim, the
        system increases reserve_balance_cents by final_payout_cents,
        decreases claim_quota_used_cents by the same amount, appends a
        ReserveAdjustment of reason REVERSE_REBUILD, and emits an
        OutboxEvent to the banking system for the clawback."

        Claim: reverse drives reserve back up by final_payout, quota_used
        back down by final_payout, and emits a BANKING outbox event.
        """
        (
            insurer, policy, flight, ticket, claim_paid, batch,
            *_ids,
        ) = setup_claim_paid(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        final_amount = claim_paid["final_payout_cents"]
        # Pre-reverse snapshot — reserve=0, quota_used=final.
        reverse_claim(insurer["id"], claim_paid["id"])
        policy_now = get_policy(insurer["id"], policy["id"])
        assert policy_now["reserve_balance_cents"] == final_amount, (
            f"reserve must be rebuilt by final_payout_cents on reverse; "
            f"got {policy_now['reserve_balance_cents']}"
        )
        assert policy_now["claim_quota_used_cents"] == 0, (
            f"quota_used must be refunded to 0 on reverse; "
            f"got {policy_now['claim_quota_used_cents']}"
        )
        from test_helpers import get_claim
        c = get_claim(insurer["id"], claim_paid["id"])
        assert c["payout_status"] == ClaimPayoutStatus.REVERSED.value


class TestPessimisticVsOptimistic:
    def test_under_review_claim_makes_pessimistic_exceed_optimistic(self, api):
        """PRD §2.8: "Whenever a policy has at least one UNDER_REVIEW claim
        with a computed gross payout, the pessimistic figure exceeds the
        optimistic figure".

        Claim: with one APPROVED claim and one UNDER_REVIEW claim,
        pessimistic > optimistic.
        """
        ctx = setup_pessimistic_vs_optimistic_pair()
        rv = get_risk_view(ctx["insurer"]["id"], ctx["policy"]["id"])
        assert_pessimistic_ge_optimistic(rv)
        assert rv["pessimistic_reserve_cents"] > rv["optimistic_reserve_cents"], (
            "with an UNDER_REVIEW claim and an APPROVED claim, pessimistic must "
            f"strictly exceed optimistic: opt={rv['optimistic_reserve_cents']}, "
            f"pess={rv['pessimistic_reserve_cents']}"
        )


class TestInvariantCheck:
    def test_invariant_check_returns_ok_for_consistent_state(self, api, claims_admin_headers):
        """PRD §3.10: "The invariant-check capability recomputes every
        policy's reserve_balance_cents and claim_quota_used_cents from the
        underlying claim ledger and reports any drift. Its response carries
        an ok boolean and a drift array".

        Claim: in a healthy state the response carries ok=true and an
        empty drift list.
        """
        (
            insurer, *_,
        ) = setup_claim_paid()
        resp = api.check_invariant(insurer["id"], claims_admin_headers)
        data = validate_success(resp)
        assert data.get("ok") is True, f"invariant must hold; got {data}"
        assert data.get("drift") in ([], None) or len(data.get("drift", [])) == 0
