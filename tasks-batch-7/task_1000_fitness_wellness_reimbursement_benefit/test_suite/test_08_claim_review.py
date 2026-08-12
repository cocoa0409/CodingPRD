"""Claim review pipeline: transitions, resubmission cap, payable min, fiscal gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_active_plan,
    create_claim_payload,
    create_employer,
    create_member,
    create_enrollment,
    create_funding_account,
    create_provider_payload,
    get_success_data,
    make_provider_operator_headers,
    member_headers,
    pay_claim,
    provider_headers,
    review_claim,
    standard_world,
    submit_approved_claim,
    submit_claim,
    submit_paid_claim,
    submit_reviewed_claim,
    tier_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


def test_claim_approve_from_submitted_rejected(api, admin_headers):
    """PRD §3.8: "A `ClaimsReviewer` may approve only a claim sitting in
    `UNDER_REVIEW`"
    PRD §3.7: "any review transition attempted from a state that does not
    permit it fails with `ERR_CLAIM_NOT_REVIEWABLE`"

    Design: Corner/state_machines/claim_approve_from_submitted_rejected
    """
    world = standard_world()
    claim = submit_claim(world, 1000, "R-1")
    resp = api.approve_claim(claim["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)
    after = get_success_data(api.get_claim(claim["id"], admin_headers))
    assert after["review_status"] == "SUBMITTED"


def test_claim_resubmit_twice_rejected(api):
    """PRD §3.7: "The owning member resubmits, moving `NEEDS_INFO →
    UNDER_REVIEW` with an optional `note`, which increments
    `resubmission_count`"
    PRD §3.7: "any review transition attempted from a state that does not
    permit it fails with `ERR_CLAIM_NOT_REVIEWABLE`"

    Design: Corner/cross_cutting_complexity_layers/claim_resubmit_twice_rejected
    """
    world = standard_world()
    claim = submit_claim(world, 1000, "R-RS")
    review_claim(claim["id"])
    get_success_data(api.request_info(claim["id"], REVIEWER))

    first = validate_success(api.resubmit_claim(claim["id"], member_headers(world)))
    assert first["review_status"] == "UNDER_REVIEW"
    assert first["resubmission_count"] == 1

    # The claim already left NEEDS_INFO, so the repeated call is state-gated.
    resp = api.resubmit_claim(claim["id"], member_headers(world))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)


class TestClaimReviewCycleResubmissionCap:
    def _cycle(self, api, world, claim_id, times):
        for _ in range(times):
            get_success_data(api.request_info(claim_id, REVIEWER))
            get_success_data(api.resubmit_claim(claim_id, member_headers(world)))

    def test_three_resubmission_cycles_succeed(self, api):
        """PRD §3.7: "The owning member resubmits, moving `NEEDS_INFO →
        UNDER_REVIEW` with an optional `note`, which increments
        `resubmission_count`; the third resubmission is the last, and a claim
        whose `resubmission_count` has already reached 3 is refused with
        `ERR_MAX_RESUBMISSIONS`."

        Design: Difficulty/non_linear_state_machine/claim_review_cycle_resubmission_cap
        """
        world = standard_world()
        claim = submit_reviewed_claim(world, 1000, "R-CYC")
        self._cycle(api, world, claim["id"], 3)
        after = get_success_data(api.get_claim(claim["id"], TEST_USERS["benefits_admin_headers"]))
        assert after["review_status"] == "UNDER_REVIEW"
        assert after["resubmission_count"] == 3

    def test_fourth_resubmit_rejected(self, api):
        """PRD §3.7: "the third resubmission is the last, and a claim whose
        `resubmission_count` has already reached 3 is refused with
        `ERR_MAX_RESUBMISSIONS`."

        Design: Difficulty/non_linear_state_machine/claim_review_cycle_resubmission_cap
        """
        world = standard_world()
        claim = submit_reviewed_claim(world, 1000, "R-CYC")
        self._cycle(api, world, claim["id"], 3)
        get_success_data(api.request_info(claim["id"], REVIEWER))
        resp = api.resubmit_claim(claim["id"], member_headers(world))
        validate_error(resp, ApiErrorId.ERR_MAX_RESUBMISSIONS)


class TestClaimPayableNestedMin:
    def _world_with_preferred_provider(self, api):
        world = standard_world()
        pref = get_success_data(api.create_provider(create_provider_payload(
            name="StudioPref", modality="STUDIO", network_tier="PREFERRED", visit_rate_cents=2000,
        ), ADMIN))
        get_success_data(api.activate_provider(pref["id"], ADMIN))
        world["preferred_provider"] = pref
        return world

    def test_per_claim_cap_binds(self, api):
        """PRD §3.8: "The resulting `approved_amount_cents` is the smallest of
        the covered amount, the tier's `per_claim_cap_cents`, the annual
        headroom, and the quarterly headroom."

        Design: Difficulty/combinatorial_formula/claim_payable_nested_min
        """
        world = self._world_with_preferred_provider(api)
        claim = submit_reviewed_claim(world, 8000, "R-1")
        # IN_NETWORK coverage 1.0 -> covered 8000; per-claim cap 5000 binds.
        approved = approve_claim(claim["id"])
        assert approved["approved_amount_cents"] == 5000, (
            f"min(8000 covered, 5000 cap, ...) must be 5000, got {approved['approved_amount_cents']}"
        )

    def test_coverage_fraction_binds(self, api):
        """PRD §3.8: "The coverage fraction is taken from the enrollment's
        tier snapshot, selected by the provider's `network_tier`:
        `in_network_pct` for an `IN_NETWORK` provider, `preferred_pct` for
        `PREFERRED`, and `out_of_network_pct` for `OUT_OF_NETWORK`. The
        covered amount is `claimed_amount_cents` multiplied by that fraction,
        rounded half up to a whole cent."
        PRD §3.8: "The resulting `approved_amount_cents` is the smallest of
        the covered amount, the tier's `per_claim_cap_cents`, the annual
        headroom, and the quarterly headroom."

        Design: Difficulty/combinatorial_formula/claim_payable_nested_min
        """
        world = self._world_with_preferred_provider(api)
        submit_paid_claim(world, 5000, "R-1")  # consume part of the quarter window
        pref = world["preferred_provider"]
        payload = create_claim_payload(
            world["enrollment"]["id"], "R-2", 6000,
            claim_type="DIRECT_PAY", service_date="2026-05-03T10:00:00Z",
        )
        payload["member_id"] = world["member"]["id"]
        claim = get_success_data(api.create_claim(payload, make_provider_operator_headers(pref["id"])))
        review_claim(claim["id"])
        # PREFERRED coverage 0.8 -> covered 4800 < cap 5000.
        approved = approve_claim(claim["id"])
        assert approved["approved_amount_cents"] == 4800, (
            f"round_half_up(6000 * 0.8) = 4800 must bind, got {approved['approved_amount_cents']}"
        )


class TestQuarterlyCapExactLanding:
    def test_exact_landing_on_cap_approved(self, api):
        """PRD §3.8: "The cap comparisons are inclusive: an approval that
        lands exactly on the quarterly cap succeeds."

        Design: Difficulty/boundary_precision_check/quarterly_cap_exact_landing
        """
        world = standard_world()
        submit_paid_claim(world, 5000, "R-Q1")  # quarter_used 5000
        claim2 = submit_reviewed_claim(world, 5000, "R-Q2", service_date="2026-05-03T10:00:00Z")
        approved = approve_claim(claim2["id"])
        assert approved["approved_amount_cents"] == 5000, (
            f"quarter remaining exactly 5000 must allow the full 5000, got {approved['approved_amount_cents']}"
        )

    def test_one_past_cap_rejected(self, api):
        """PRD §3.8: "If the quarterly headroom is zero or less, the claim is
        rejected with `ERR_QUARTERLY_CAP_EXCEEDED`"
        PRD §3.8: "When approval fails on fiscal grounds, the rejection error
        is chosen in a fixed order — the quarterly window is always evaluated
        before the annual window."

        Design: Difficulty/boundary_precision_check/quarterly_cap_exact_landing
        """
        world = standard_world()
        submit_paid_claim(world, 5000, "R-Q1")
        submit_paid_claim(world, 5000, "R-Q2", service_date="2026-05-03T10:00:00Z")
        claim3 = submit_reviewed_claim(world, 100, "R-Q3", service_date="2026-05-04T10:00:00Z")
        resp = api.approve_claim(claim3["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_QUARTERLY_CAP_EXCEEDED)


class TestApproveFundingSuspendedBeatsFundingInsufficient:
    def _setup(self, api):
        """Funding 3000 then SUSPENDED; claim 5000 UNDER_REVIEW."""
        world = standard_world(funding_cents=3000)
        claim = submit_reviewed_claim(world, 5000, "R-1")
        validate_success(api.suspend_funding_account(world["funding"]["id"], ADMIN))
        return world, claim

    def test_state_error_wins(self, api):
        """PRD §3.8: "the approval gate checks, in order: the claim's
        `fraud_hold` must be false (`ERR_FRAUD_HOLD`); the enrollment must be
        `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`); the funding account for the
        employer and benefit year must not be `SUSPENDED`
        (`ERR_FUNDING_NOT_ACTIVE`); and the computed payable amount must be
        positive and coverable by funding."
        PRD §2.9: "4. **State preconditions** — the target entity must be in
        the state its transition requires" ... "10. **Fiscal windows at
        approval** — quarterly headroom first, then annual headroom, then
        funding availability."

        Design: Difficulty/priority_pair_validation_conflict/approve_funding_suspended_beats_funding_insufficient
        """
        world, claim = self._setup(api)
        resp = api.approve_claim(claim["id"], REVIEWER)
        err = validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_ACTIVE)
        # available 3000 < approvable 5000, yet the state check fires first.
        assert err["error_id"] != "ERR_FUNDING_INSUFFICIENT"

    def test_claim_stays_under_review(self, api, admin_headers):
        """PRD §3.8: "the funding account for the employer and benefit year
        must not be `SUSPENDED` (`ERR_FUNDING_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/approve_funding_suspended_beats_funding_insufficient
        """
        world, claim = self._setup(api)
        validate_error(api.approve_claim(claim["id"], REVIEWER), ApiErrorId.ERR_FUNDING_NOT_ACTIVE)
        after = get_success_data(api.get_claim(claim["id"], admin_headers))
        assert after["review_status"] == "UNDER_REVIEW"


class TestFundingReservedEvaluationOrder:
    """Funded 10000, claim1 APPROVED 4000 (available 6000), claim2 approvable
    at 7000 fails on funding availability."""

    def _setup(self, api):
        tiers = [tier_payload(annual_allowance_cents=30000, quarterly_cap_cents=20000,
                              per_claim_cap_cents=8000)]
        world = standard_world(funding_cents=10000, tiers=tiers,
                               member_overrides={"external_ref": "E9", "full_name": "Mem Nine"})
        submit_approved_claim(world, 4000, "R-1")
        claim2 = submit_reviewed_claim(world, 7000, "R-2", service_date="2026-05-03T10:00:00Z")
        return world, claim2

    def test_second_approval_fails_funding_insufficient(self, api):
        """PRD §3.8: "otherwise, if the funding account's `available_cents` is
        below the approved amount, with `ERR_FUNDING_INSUFFICIENT`."
        PRD §2.10: "Second, open approvals are summed as the
        `approved_amount_cents` of claims that are `APPROVED` and `UNPAID` on
        plans belonging to the account's employer and benefit year — and the
        account's `reserved_cents` is derived from those claims, never
        re-summed from ledger entries."

        Design: Difficulty/combinatorial_formula/funding_reserved_evaluation_order
        """
        world, claim2 = self._setup(api)
        resp = api.approve_claim(claim2["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_FUNDING_INSUFFICIENT)  # available 6000 < 7000

    def test_hold_leaves_account_state_untouched(self, api, admin_headers):
        """PRD §3.8: "a `HOLD` entry is appended to the ledger, and the
        account's `reserved_cents` rises while its `available_cents` falls by
        the approved amount."

        Design: Difficulty/combinatorial_formula/funding_reserved_evaluation_order
        """
        world, claim2 = self._setup(api)
        validate_error(api.approve_claim(claim2["id"], REVIEWER), ApiErrorId.ERR_FUNDING_INSUFFICIENT)

        after_claim = get_success_data(api.get_claim(claim2["id"], admin_headers))
        assert after_claim["review_status"] == "UNDER_REVIEW"
        account = get_success_data(api.get_funding_account(world["funding"]["id"], admin_headers))
        assert account["available_cents"] == 6000, f"10000 - 4000 hold, got {account['available_cents']}"
        assert account["reserved_cents"] == 4000, f"open approvals sum to 4000, got {account['reserved_cents']}"
