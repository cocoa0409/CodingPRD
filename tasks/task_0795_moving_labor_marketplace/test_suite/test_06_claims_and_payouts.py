"""Damage-claim settlement variants, the claim->payout reversal cascade, validation
precedence on approval, payout reversal invariants, and the deny path."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_config, create_booked_job, setup_settled_job_with_payout,
    create_claim_payload, make_customer_headers, ADMIN, api_client,
)

WINDOW_START = "2026-03-10T09:00:00Z"
WINDOW_END = "2026-03-10T12:00:00Z"


class TestClaimSettlementVariants:
    """Design: Difficulty/dual_variant_calc/claim_settlement_basic_vs_full_diverge"""

    def _approved_claim(self, api, policy_tier, policy_overrides, claimed):
        rate_card, policy, customer = create_config(
            api, policy_tier=policy_tier, policy_overrides=policy_overrides,
        )
        booked, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0, window_start=WINDOW_START, window_end=WINDOW_END,
        )
        claim = validate_success(api.create_claim(
            create_claim_payload(booked["id"], claimed), make_customer_headers(customer["id"]),
        ), 201)
        validate_success(api.review_claim(claim["id"], ADMIN))
        return validate_success(api.approve_claim(claim["id"], ADMIN))

    def test_basic_tier_subtracts_deductible(self, api):
        """PRD §3.8: "Under the `BASIC` tier, `insurance_covered_cents` is the approved amount
        minus the policy's `deductible_cents`, but never less than 0 — the deductible is
        subtracted with no percentage haircut."

        Claimed 150000 under a BASIC policy (cap 200000, deductible 10000) settles to 140000.

        Design: Difficulty/dual_variant_calc/claim_settlement_basic_vs_full_diverge
        """
        approved = self._approved_claim(api, "BASIC", None, 150000)
        assert approved["insurance_covered_cents"] == 140000

    def test_full_tier_applies_coverage_pct(self, api):
        """PRD §3.8: "Under the `FULL` tier, `insurance_covered_cents` is the approved amount
        multiplied by the policy's `coverage_pct`, rounded half up to cents, with no
        deductible."

        The identical 150000 claim under a FULL policy (cap 1000000, coverage_pct 0.9)
        settles to 135000, diverging from the BASIC path.

        Design: Difficulty/dual_variant_calc/claim_settlement_basic_vs_full_diverge
        """
        approved = self._approved_claim(
            api, "FULL",
            {"coverage_cap_cents": 1000000, "deductible_cents": 0, "coverage_pct": 0.9},
            150000,
        )
        assert approved["insurance_covered_cents"] == 135000


class TestClaimApprovalReversesPayout:
    """Design: Difficulty/transitive_cascade/claim_approval_reverses_payout"""

    def _approve_claim_against_settled_job(self, api):
        env = setup_settled_job_with_payout(api)  # payout 14100, lifetime 14100
        claim = validate_success(api.create_claim(
            create_claim_payload(env["job"]["id"], 150000,
                                 damage_description="broke table",
                                 responsible_helper_id=env["helper"]["id"]),
            make_customer_headers(env["customer"]["id"]),
        ), 201)
        validate_success(api.review_claim(claim["id"], ADMIN))
        approved = validate_success(api.approve_claim(claim["id"], ADMIN))
        return env, approved

    def test_approval_reverses_responsible_helper_payout(self, api):
        """PRD §3.8: "if the claim carries a `responsible_helper_id` and that helper has a
        `RELEASED` payout for this same job, that payout is transitioned
        `RELEASED → REVERSED`, which in turn recomputes the helper's `lifetime_payout_cents`."
        PRD §3.7: "the affected helper's `lifetime_payout_cents` is recomputed to exclude the
        reversed amount."

        Design: Difficulty/transitive_cascade/claim_approval_reverses_payout
        """
        env, _approved = self._approve_claim_against_settled_job(api)
        payout = validate_success(api.get_payout(env["payout"]["id"], ADMIN))
        helper = validate_success(api.get_helper(env["helper"]["id"], ADMIN))
        assert payout["status"] == "REVERSED"
        assert helper["lifetime_payout_cents"] == 0

    def test_approval_credits_customer_wallet(self, api):
        """PRD §3.8: "the customer's `wallet_credit_cents` is recomputed as the sum of
        `insurance_covered_cents` over all `APPROVED` claims filed on that customer's jobs."

        The BASIC settlement of the 150000 claim (covered 140000) is credited to the wallet.

        Design: Difficulty/transitive_cascade/claim_approval_reverses_payout
        """
        env, approved = self._approve_claim_against_settled_job(api)
        assert approved["status"] == "APPROVED"
        assert approved["insurance_covered_cents"] == 140000
        customer = validate_success(api.get_customer(env["customer"]["id"], ADMIN))
        assert customer["wallet_credit_cents"] == 140000


class TestApproveWrongStateBeatsCoverageCap:
    """Design: Difficulty/priority_pair_validation_conflict/claim_approve_wrong_state_beats_coverage_cap"""

    def _filed_over_cap_claim(self, api):
        rate_card, policy, customer = create_config(api)  # BASIC cap 200000
        booked, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0, window_start=WINDOW_START, window_end=WINDOW_END,
        )
        claim = validate_success(api.create_claim(
            create_claim_payload(booked["id"], 300000, damage_description="big"),
            make_customer_headers(customer["id"]),
        ), 201)
        return claim  # left FILED (never reviewed); 300000 > cap 200000

    def test_approve_filed_claim_returns_invalid_state(self, api):
        """PRD §2.8: "For a state-transition operation, the target resource's current state is
        checked; an operation attempted from an ineligible state yields `ERR_INVALID_STATE`
        (409)." PRD §2.8: "Body-level request validity and the domain-specific business rules
        described in Section 3 are checked last".

        Approving a FILED (not UNDER_REVIEW) claim whose amount also exceeds the cap fails the
        state check first.

        Design: Difficulty/priority_pair_validation_conflict/claim_approve_wrong_state_beats_coverage_cap
        """
        claim = self._filed_over_cap_claim(api)
        resp = api.approve_claim(claim["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_filed_claim_unchanged_after_blocked_approve(self, api):
        """PRD §3.8: "a `FILED` claim is moved to `UNDER_REVIEW`, and from `UNDER_REVIEW` it
        is either approved to `APPROVED` or denied to `DENIED`." A blocked approve leaves the
        claim in FILED.

        Design: Difficulty/priority_pair_validation_conflict/claim_approve_wrong_state_beats_coverage_cap
        """
        claim = self._filed_over_cap_claim(api)
        api.approve_claim(claim["id"], ADMIN)
        after = validate_success(api.get_claim(claim["id"], ADMIN))
        assert after["status"] == "FILED"


class TestPayoutLedgerConservedOnReversal:
    """Design: Difficulty/compensating_invariant/payout_ledger_conserved_on_reversal"""

    def test_reverse_payout_marks_it_reversed(self, api):
        """PRD §3.7: "An administrator may reverse a `RELEASED` payout directly ... either way
        the payout transitions `RELEASED → REVERSED`".

        Design: Difficulty/compensating_invariant/payout_ledger_conserved_on_reversal
        """
        env = setup_settled_job_with_payout(api)
        reversed_payout = validate_success(api.reverse_payout(env["payout"]["id"], ADMIN))
        assert reversed_payout["status"] == "REVERSED"

    def test_reverse_payout_recomputes_lifetime_to_zero(self, api):
        """PRD §3.7: "the affected helper's `lifetime_payout_cents` is recomputed to exclude
        the reversed amount." PRD §3.7: "the sum of `total_payout_cents` over all of that
        helper's payouts still in status `RELEASED` (payouts in status `REVERSED` are
        excluded)."

        Reversing the sole 14100 payout returns lifetime_payout_cents to 0.

        Design: Difficulty/compensating_invariant/payout_ledger_conserved_on_reversal
        """
        env = setup_settled_job_with_payout(api)
        validate_success(api.reverse_payout(env["payout"]["id"], ADMIN))
        helper = validate_success(api.get_helper(env["helper"]["id"], ADMIN))
        assert helper["lifetime_payout_cents"] == 0


def test_deny_under_review_claim_credits_no_wallet(api):
    """PRD §3.8: "from `UNDER_REVIEW` it is either approved to `APPROVED` or denied to
    `DENIED`." Denial leaves the customer's wallet at 0 (no covered amount is credited).

    Design: Corner/state_machines/claim_deny_path
    """
    rate_card, policy, customer = create_config(api)
    booked, _q = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=3.0, window_start="2026-03-11T09:00:00Z",
        window_end="2026-03-11T12:00:00Z",
    )
    claim = validate_success(api.create_claim(
        create_claim_payload(booked["id"], 50000, damage_description="minor"),
        make_customer_headers(customer["id"]),
    ), 201)
    validate_success(api.review_claim(claim["id"], ADMIN))
    denied = validate_success(api.deny_claim(claim["id"], ADMIN))
    assert denied["status"] == "DENIED"
    refreshed = validate_success(api.get_customer(customer["id"], ADMIN))
    assert refreshed["wallet_credit_cents"] == 0
