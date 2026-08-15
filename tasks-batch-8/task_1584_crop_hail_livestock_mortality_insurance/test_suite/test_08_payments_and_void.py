"""Indemnity payment issue and void — the claim-side financial invariant
(PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    approve_claim,
    assert_indemnity_payment,
    issue_payment,
    read_claim,
    read_policy,
    setup_hail_claim_under_review,
    validate_success,
)

APPROVER = TEST_USERS["claims_approver_headers"]


class TestVoidRestoresClaimPipeline:
    def _setup_approved_claim(self, api):
        """10-acre policy (premium 13_320; reserve 7_992) with a claim decided
        PARTIAL at 5_000 — claim APPROVED, reserve 2_992."""
        ctx = setup_hail_claim_under_review(acres=10, observed_percent_damage_pct=10)
        cid, pid = ctx["carrier_id"], ctx["policy_id"]
        approve_claim(cid, pid, ctx["claim"]["id"], 5_000, decision="PARTIAL")
        pre = read_policy(cid, pid)
        assert pre["premium_reserve_cents"] == 2_992
        return ctx

    def test_void_reopens_claim_with_final_indemnity_intact(self, api):
        """PRD §3.8: "Alternatively, a payment may be voided within twenty-four
        hours of its `issued_at`, which moves it to `VOID` and re-opens the claim
        from `PAID` back to `APPROVED` so a corrected payment can be issued; a
        void attempted after the twenty-four-hour window is rejected with
        `ERR_VOID_WINDOW_EXPIRED` (HTTP 422)."
        PRD §3.8: "The issued payment snapshots its `amount_cents` from the
        claim's `final_indemnity_cents` at the moment of issue, stamps
        `issued_at` from the logical clock, records its `claim_id`, begins in
        `ISSUED` status, and moves the claim from `APPROVED` to `PAID`."

        Design: Difficulty/compensating_invariant/indemnity_payment_void_restores_claim_state_and_amount_unchanged
        """
        ctx = self._setup_approved_claim(api)
        cid, pid = ctx["carrier_id"], ctx["policy_id"]
        payment = issue_payment(cid, pid, ctx["claim"]["id"])
        assert_indemnity_payment(payment)
        assert payment["amount_cents"] == 5_000
        assert payment["status"] == "ISSUED"
        assert read_claim(cid, pid, ctx["claim"]["id"])["claim_state"] == "PAID"

        res = api.void_indemnity_payment(cid, pid, ctx["claim"]["id"],
                                         payment["id"], APPROVER)
        voided = validate_success(res, 200)
        assert voided["status"] == "VOID"
        claim = read_claim(cid, pid, ctx["claim"]["id"])
        assert claim["claim_state"] == "APPROVED", "void re-opens the claim"
        assert claim["final_indemnity_cents"] == 5_000, (
            "the final indemnity is untouched by issue-then-void"
        )

    def test_void_leaves_premium_reserve_unchanged(self, api):
        """PRD §3.8: "Approval cascades widely. The claim moves from
        `UNDER_REVIEW` to `APPROVED`; the coverage unit settles, moving from
        `UNDER_CLAIM` to `SETTLED`; the grower's `prior_claims_count` increments
        by one, which can lift the surcharge tier on future applications; and the
        policy's `premium_reserve_cents` is recomputed as sixty percent of
        `premium_cents` rounded down to a whole cent, less the sum of
        `final_indemnity_cents` across the policy's `APPROVED` and `PAID` claims,
        floored at zero — with the policy's `version` incrementing as the cascade
        lands."
        The claim is in `APPROVED` or `PAID` throughout the issue-then-void
        sequence, so its 5_000-cent final indemnity is counted at every step and
        the reserve holds at 2_992.

        Design: Difficulty/compensating_invariant/indemnity_payment_void_restores_claim_state_and_amount_unchanged
        """
        ctx = self._setup_approved_claim(api)
        cid, pid = ctx["carrier_id"], ctx["policy_id"]
        reserve_pre_issue = read_policy(cid, pid)["premium_reserve_cents"]

        payment = issue_payment(cid, pid, ctx["claim"]["id"])
        assert read_policy(cid, pid)["premium_reserve_cents"] == reserve_pre_issue
        validate_success(
            api.void_indemnity_payment(cid, pid, ctx["claim"]["id"],
                                       payment["id"], APPROVER),
            200,
        )
        policy = read_policy(cid, pid)
        assert policy["premium_reserve_cents"] == reserve_pre_issue == 2_992, (
            "reserve consumed at approval is unchanged by issue + void"
        )
