"""Refusals on the settlement side: authority, ceilings, clearance and available cash."""

from test_helpers import (
    TEST_USERS,
    api_client,
    approve,
    assert_estate_ledger_identity,
    claim_payload,
    distribution_payload,
    engage_vendor,
    get_success_data,
    read_claim,
    read_insolvency,
    read_policy,
    read_premium_refund,
    recommend,
    remit_estate_cash,
    screen_claim,
    setup_approved_claim_with_estate_cash,
    setup_claim_under_adjustment,
    setup_policy_with_premium_refund,
    setup_screened_claim,
    validate_error,
)

ADMIN = TEST_USERS["association_admin_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
BIG_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 4_500_000,
}
SMALL_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
NARROW_AUTHORITY_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 2_500_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
AMPLE_AUTHORITY_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 3_000_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
SMALL_LOSS_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 1_000_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}


class TestRecommendationCeilings:
    """A recommendation is bounded twice over: by the engagement, and by the statute."""

    def test_a_number_above_the_engagement_authority_is_refused(self):
        """The submitted `recommended_amount_cents` must be at or below that engagement's
        `settlement_authority_cents`, else `ERR_ADJUSTER_AUTHORITY_EXCEEDED`.

        On success the claim moves `ADJUSTING → RECOMMENDED`, `recommended_amount_cents` is stored,
        `recommended_by_vendor_name` is set to the `vendor_name` of the acting engagement,
        `recommended_at_utc` is stamped from the logical clock, and the claim's `version` is
        incremented by one.

        Design: Corner/validations/recommending_above_the_engagement_authority_is_refused
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(BIG_LOSS_CLAIM),
            assignment_overrides=dict(NARROW_AUTHORITY_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        claim = env["claim"]
        assert claim["status"] == "ADJUSTING", claim["status"]
        assert claim["net_payable_cents"] == 3_000_000, (
            f"the per-claim cap already trimmed the payable, got {claim['net_payable_cents']}"
        )
        assert env["assignment"]["settlement_authority_cents"] == 2_500_000

        validate_error(
            api_client.recommend_claim(
                claim["id"], {"recommended_amount_cents": 3_000_000}, env["adjuster_headers"]
            ),
            "ERR_ADJUSTER_AUTHORITY_EXCEEDED",
            422,
        )

        after = read_claim(claim["id"])
        assert after["status"] == "ADJUSTING", (
            f"a figure the vendor cannot bind the estate to stores nothing, got {after['status']}"
        )
        assert after["recommended_amount_cents"] is None, after["recommended_amount_cents"]
        assert after["recommended_by_vendor_name"] is None
        assert after["recommended_at_utc"] is None
        assert after["version"] == claim["version"], (
            f"a refusal bumps no version, got {after['version']} after {claim['version']}"
        )

        accepted = recommend(env, 2_500_000)
        assert accepted["status"] == "RECOMMENDED", accepted["status"]
        assert accepted["recommended_amount_cents"] == 2_500_000, (
            "the authority figure itself is within authority, got "
            f"{accepted['recommended_amount_cents']}"
        )

    def test_a_number_above_the_statutory_payable_is_refused(self):
        """And it must be at or below the claim's `net_payable_cents`, else `ERR_OVERPAYMENT` — the
        association will not recommend more than it is statutorily liable for.

        The amount tendered does not exceed the outstanding balance — `recommended_amount_cents` at or
        below `net_payable_cents` on a recommendation, and `amount_cents` at or below
        `levied_amount_cents` less `paid_amount_cents` on a member payment → `ERR_OVERPAYMENT`
        (HTTP 422), on `POST /claims/{id}/recommend` and `POST /member-assessments/{id}/payments`.

        Design: Corner/validations/recommending_above_the_statutory_payable_is_refused
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(SMALL_LOSS_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        claim = env["claim"]
        assert claim["net_payable_cents"] == 890_000, (
            f"the 900000 loss less the 10000 statutory deductible, got "
            f"{claim['net_payable_cents']}"
        )
        assert env["assignment"]["settlement_authority_cents"] == 1_000_000, (
            "the vendor has ample authority, so only the statutory ceiling can bite"
        )

        validate_error(
            api_client.recommend_claim(
                claim["id"], {"recommended_amount_cents": 950_000}, env["adjuster_headers"]
            ),
            "ERR_OVERPAYMENT",
            422,
        )

        after = read_claim(claim["id"])
        assert after["status"] == "ADJUSTING", after["status"]
        assert after["recommended_amount_cents"] is None, after["recommended_amount_cents"]
        assert after["net_payable_cents"] == 890_000, after["net_payable_cents"]
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, (
            f"no reserve is booked before approval, got {insolvency['reserved_claim_cents']}"
        )


class TestApprovalAggregateRoom:
    """A sibling approval consumes the aggregate and blocks the next one outright."""

    def test_a_sibling_approval_that_ate_the_aggregate_blocks_this_one(self):
        """Three business guards apply, in the priority order set out in the validation cascade: first
        the segregation-of-duties check, which refuses the approval with `ERR_SEGREGATION_OF_DUTIES`
        when the acting `X-User-ID` equals the claim's `screened_by_user_id`; then the non-duplication
        check, which refuses with `ERR_OTHER_INSURANCE_NOT_EXHAUSTED` unless every other-insurance
        layer on the claim has reached `EXHAUSTED` or `CARRIER_DENIED`; then the aggregate-cap check,
        which requires the claim's currently stored `net_payable_cents` to be at or below the line's
        `per_policy_aggregate_cap_cents` less the policy's `aggregate_paid_cents`, floored at 0, and
        refuses with `ERR_AGGREGATE_CAP_EXHAUSTED` otherwise. That last check deliberately reads the
        value stored at screening time and runs
        *before* the approval recompute, which means an earlier approval of a sibling claim that
        consumed the policy aggregate in the meantime will block this approval rather than silently
        shrinking it.

        Design: Corner/validations/approving_past_the_policy_aggregate_cap_is_refused
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(BIG_LOSS_CLAIM),
            assignment_overrides=dict(AMPLE_AUTHORITY_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        first = env["claim"]
        first_adjuster_headers = env["adjuster_headers"]
        assert first["net_payable_cents"] == 3_000_000, first["net_payable_cents"]

        sibling = get_success_data(
            api_client.create_claim(
                claim_payload(
                    env["insolvency"]["id"],
                    env["policy"]["id"],
                    claim_number="C-2",
                    claimant_name="Cora Diaz",
                    loss_date="2026-01-20",
                    gross_loss_cents=4_500_000,
                ),
                ANALYST,
            ),
            201,
        )
        env["claim"] = sibling
        screen_claim(env)
        assert env["claim"]["net_payable_cents"] == 3_000_000, (
            "both claims are priced while the whole aggregate is still free, got "
            f"{env['claim']['net_payable_cents']}"
        )
        engage_vendor(env, **AMPLE_AUTHORITY_ADJUSTER)
        recommend(env, 3_000_000)
        second_id = env["claim"]["id"]

        env["claim"] = get_success_data(
            api_client.recommend_claim(
                first["id"],
                {"recommended_amount_cents": 3_000_000},
                first_adjuster_headers,
            )
        )
        approved = approve(env)
        assert approved["status"] == "APPROVED", approved["status"]
        assert approved["net_payable_cents"] == 3_000_000, approved["net_payable_cents"]

        validate_error(
            api_client.approve_claim(second_id, TEST_USERS["claims_committee_officer_headers"]),
            "ERR_AGGREGATE_CAP_EXHAUSTED",
            422,
        )

        blocked = read_claim(second_id)
        assert blocked["status"] == "RECOMMENDED", (
            f"the approval is refused outright rather than shrunk, got {blocked['status']}"
        )
        assert blocked["net_payable_cents"] == 3_000_000, (
            "the stored payable is left exactly as screening wrote it, got "
            f"{blocked['net_payable_cents']}"
        )
        assert blocked["approved_by_user_id"] is None

        policy = read_policy(env["policy"]["id"])
        assert policy["aggregate_paid_cents"] == 3_000_000, (
            "only the approved sibling consumed aggregate room, got "
            f"{policy['aggregate_paid_cents']}"
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 3_000_000, (
            f"one hard liability, not two, got {insolvency['reserved_claim_cents']}"
        )


class TestClosureClearanceChecks:
    """Neither an open claim nor an unpaid refund lets the file wind up."""

    def test_a_claim_still_in_screening_blocks_the_close(self):
        """If any covered claim of the file remains in `RECEIVED`, `SCREENED_ELIGIBLE`, `ADJUSTING`,
        `RECOMMENDED`, `REFERRAL_PENDING`, `APPROVED` or `PARTIALLY_PAID`, the close is refused with
        `ERR_CLAIMS_OUTSTANDING`; claims already in `DENIED_NOT_COVERED`, `REFERRED_OUT` or `PAID` are
        settled business and do not block.

        Design: Corner/validations/closing_the_file_with_a_claim_still_open_is_refused
        """
        env = setup_screened_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        assert env["claim"]["status"] == "SCREENED_ELIGIBLE", env["claim"]["status"]
        remit_estate_cash(env["insolvency"]["id"], 500_000, "RM-1")

        validate_error(
            api_client.close_insolvency(env["insolvency"]["id"], ADMIN),
            "ERR_CLAIMS_OUTSTANDING",
            409,
        )

        after = read_insolvency(env["insolvency"]["id"])
        assert_estate_ledger_identity(after)
        assert after["status"] == "TRIGGERED", (
            f"the file stays open while a claim is unresolved, got {after['status']}"
        )
        assert after["estate_undistributed_cents"] == 500_000, (
            f"the cash stays in hand, got {after['estate_undistributed_cents']}"
        )
        assert after["estate_returned_cents"] == 0, (
            f"no cash may be returned to the receiver yet, got {after['estate_returned_cents']}"
        )
        assert read_claim(env["claim"]["id"])["status"] == "SCREENED_ELIGIBLE"

    def test_a_pending_unearned_premium_refund_blocks_the_close(self):
        """If any unearned premium refund on a policy of the file remains in `PENDING` or
        `PARTIALLY_PAID`, the close is refused with `ERR_REFUNDS_OUTSTANDING`.

        Design: Corner/validations/closing_the_file_with_a_pending_refund_is_refused
        """
        env = setup_policy_with_premium_refund(
            refund_method="PRO_RATA", policy_overrides=dict(LIVE_TERM)
        )
        assert env["refund"]["status"] == "PENDING", env["refund"]["status"]
        assert env["refund"]["computed_refund_cents"] == 604_932, (
            env["refund"]["computed_refund_cents"]
        )

        validate_error(
            api_client.close_insolvency(env["insolvency"]["id"], ADMIN),
            "ERR_REFUNDS_OUTSTANDING",
            409,
        )

        after = read_insolvency(env["insolvency"]["id"])
        assert_estate_ledger_identity(after)
        assert after["status"] == "TRIGGERED", after["status"]
        assert after["pending_up_liability_cents"] == 604_932, (
            f"the refund exposure is still owed, got {after['pending_up_liability_cents']}"
        )
        refund = read_premium_refund(env["policy"]["id"])
        assert refund["status"] == "PENDING", refund["status"]
        assert refund["paid_amount_cents"] == 0, refund["paid_amount_cents"]


class TestDistributionIsBoundedByTheCashInHand:
    """A run may only spread money the association actually holds."""

    def test_a_run_larger_than_the_undistributed_balance_is_refused(self):
        """The amount must be at or below the file's current `estate_undistributed_cents`, else the run
        is refused with `ERR_INSUFFICIENT_ESTATE_FUNDS`; the association cannot distribute cash it does
        not hold.

        Design: Corner/validations/distributing_more_than_the_undistributed_balance_is_refused
        """
        env = setup_approved_claim_with_estate_cash(
            remitted_cents=500_000,
            recommended_amount_cents=890_000,
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(SMALL_LOSS_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        before = read_insolvency(env["insolvency"]["id"])
        assert before["estate_undistributed_cents"] == 500_000, (
            before["estate_undistributed_cents"]
        )
        assert before["reserved_claim_cents"] == 890_000, before["reserved_claim_cents"]

        validate_error(
            api_client.run_distribution(
                before["id"], distribution_payload(600_000, before["version"]), ADMIN
            ),
            "ERR_INSUFFICIENT_ESTATE_FUNDS",
            422,
        )

        after = read_insolvency(before["id"])
        assert_estate_ledger_identity(after)
        assert after["distribution_sequence"] == 0, (
            f"the refused run is not numbered, got {after['distribution_sequence']}"
        )
        assert after["estate_undistributed_cents"] == 500_000, (
            after["estate_undistributed_cents"]
        )
        assert after["estate_distributed_cents"] == 0, after["estate_distributed_cents"]

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "APPROVED", claim["status"]
        assert claim["paid_amount_cents"] == 0, (
            f"no claimant is paid out of a refused run, got {claim['paid_amount_cents']}"
        )
