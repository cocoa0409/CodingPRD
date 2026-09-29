"""Money arithmetic: retention credit, cap boundaries, rounding, accrual and the waterfall."""

from test_helpers import (
    TEST_USERS,
    advance_other_insurance,
    api_client,
    approve,
    assert_covered_claim,
    assert_member_assessment,
    assert_unearned_premium_refund,
    claim_payload,
    create_policy,
    engage_vendor,
    get_success_data,
    post_vendor_invoice,
    read_claim,
    read_insolvency,
    read_premium_refund,
    recommend,
    register_other_insurance,
    remit_estate_cash,
    run_distribution,
    screen_claim,
    setup_approved_claim,
    setup_certified_assessment,
    setup_claim_under_adjustment,
    setup_declared_insolvency,
    setup_screened_claim,
    setup_two_policies_with_pending_refunds,
    trigger_insolvency,
)

ANALYST = TEST_USERS["coverage_analyst_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
FULLY_COLLATERALISED = {
    "policy_number": "PA-A",
    "policyholder_name": "Ada Renner",
    "large_deductible_cents": 500_000,
    "collateral_held_cents": 500_000,
}
UNDER_COLLATERALISED = {
    "policy_number": "PA-B",
    "policyholder_name": "Boris Ilic",
    "large_deductible_cents": 500_000,
    "collateral_held_cents": 200_000,
}
KESTREL_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
CAP_RATE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 12_345_678,
        "annual_cap_rate_bps": 175,
    }
]


def _present(env: dict, policy: dict, **overrides) -> dict:
    """Present one claim against a named policy of the environment's file."""
    return get_success_data(
        api_client.create_claim(
            claim_payload(env["insolvency"]["id"], policy["id"], **overrides), ANALYST
        ),
        201,
    )


def _screen_covered(claim_id: str) -> dict:
    return get_success_data(
        api_client.screen_claim(claim_id, {"decision": "COVERED"}, ANALYST)
    )


class TestRetainedLayerAndCapBoundaries:
    """What the association actually owes on one loss, term by term."""

    def test_only_the_collateral_actually_posted_is_credited_against_the_loss(self):
        """Second, `attachment_point_cents` is whichever is smaller of two figures on the parent
        policy: the sum of `large_deductible_cents` and `self_insured_retention_cents`, or
        `collateral_held_cents` on its own. This is the self-funded retention credit rule in force: the
        insured's retained layer is credited against the association's exposure only up to the
        collateral actually held by the receiver, because collateral is the only part of the retention
        the receiver can genuinely realise. Third, `covered_layer_cents` is `covered_basis_cents` less
        `attachment_point_cents`, floored at 0 so it never goes negative.

        Design: Corner/calculations/retained_layer_is_credited_only_up_to_the_collateral_actually_held
        """
        env = setup_declared_insolvency(policy_overrides=dict(FULLY_COLLATERALISED))
        under = create_policy(env["insolvency"]["id"], **UNDER_COLLATERALISED)
        env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])

        full_claim = _present(
            env, env["policy"], claim_number="C-A", claimant_name="Ben Ortiz",
            gross_loss_cents=2_000_000,
        )
        thin_claim = _present(
            env, under, claim_number="C-B", claimant_name="Cora Diaz",
            gross_loss_cents=2_000_000,
        )

        priced_full = _screen_covered(full_claim["id"])
        priced_thin = _screen_covered(thin_claim["id"])

        assert_covered_claim(priced_full)
        assert priced_full["covered_layer_cents"] == 1_500_000, (
            "the whole 500000 retention is credited when it is fully collateralised, got "
            f"{priced_full['covered_layer_cents']}"
        )
        assert priced_full["net_payable_cents"] == 1_490_000, priced_full["net_payable_cents"]
        assert priced_full["cap_binding"] == "NONE", priced_full["cap_binding"]

        assert priced_thin["covered_layer_cents"] == 1_800_000, (
            "only the 200000 actually posted may be credited, got "
            f"{priced_thin['covered_layer_cents']}"
        )
        assert priced_thin["net_payable_cents"] == 1_790_000, priced_thin["net_payable_cents"]
        assert priced_thin["cap_binding"] == "NONE", priced_thin["cap_binding"]

    def test_the_per_claim_cap_bites_only_strictly_above_the_ceiling(self):
        """Finally `cap_binding` records which statutory ceiling actually bit. It is
        `PER_POLICY_AGGREGATE` when `net_payable_cents` came out strictly below the statutory figure,
        meaning the policy aggregate was the binding constraint. Otherwise it is `PER_CLAIM` when the
        fully uncapped figure — `covered_layer_cents` less the other-insurance recovery less the
        statutory deductible, floored at 0 — is strictly greater than `per_claim_cap_cents`. Otherwise
        it is `NONE`.

        Design: Corner/calculations/per_claim_cap_boundary_at_one_cent_below_at_and_above
        """
        env = setup_declared_insolvency(policy_overrides=dict(LIVE_TERM))
        env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])

        below = _present(
            env, env["policy"], claim_number="C-1", claimant_name="Ben Ortiz",
            gross_loss_cents=3_009_999,
        )
        at = _present(
            env, env["policy"], claim_number="C-2", claimant_name="Ben Ortiz",
            gross_loss_cents=3_010_000,
        )
        above = _present(
            env, env["policy"], claim_number="C-3", claimant_name="Ben Ortiz",
            gross_loss_cents=3_010_001,
        )

        priced_below = _screen_covered(below["id"])
        priced_at = _screen_covered(at["id"])
        priced_above = _screen_covered(above["id"])

        assert priced_below["net_payable_cents"] == 2_999_999, priced_below["net_payable_cents"]
        assert priced_below["cap_binding"] == "NONE", priced_below["cap_binding"]

        assert priced_at["net_payable_cents"] == 3_000_000, priced_at["net_payable_cents"]
        assert priced_at["cap_binding"] == "NONE", (
            "an uncapped figure equal to the cap has not exceeded it, got "
            f"{priced_at['cap_binding']}"
        )

        assert priced_above["net_payable_cents"] == 3_000_000, priced_above["net_payable_cents"]
        assert priced_above["cap_binding"] == "PER_CLAIM", (
            f"one cent above the ceiling is where the cap bites, got {priced_above['cap_binding']}"
        )

        for priced in (priced_below, priced_at, priced_above):
            assert priced["alt_net_payable_cents"] == 2_990_000, (
                "capping before offsetting yields the same alternative figure on all three, got "
                f"{priced['alt_net_payable_cents']}"
            )


class TestMoneyRoundingAndAccrual:
    """Where the arithmetic rounds, and where it merely accumulates."""

    def test_the_member_ceiling_rounds_half_up_to_a_whole_cent(self):
        """Before any spreading, each pooled member's ceiling is computed once: its `cap_amount_cents`
        is its `direct_written_premium_cents` multiplied by its `annual_cap_rate_bps`, divided by ten
        thousand, rounded half up to whole cents.

        Design: Corner/calculations/member_cap_amount_rounds_half_up_to_whole_cents
        """
        env = setup_certified_assessment(
            member_specs=CAP_RATE_MEMBER,
            needed_amount_cents=100_000,
            policy_overrides=dict(LIVE_TERM),
        )
        assessment = env["assessment"]
        invoice = env["member_assessment"]

        assert_member_assessment(invoice)
        assert invoice["cap_amount_cents"] == 216_049, (
            "12345678 at 175 bps is 216049.365, which rounds half up to 216049, got "
            f"{invoice['cap_amount_cents']}"
        )
        assert invoice["levied_amount_cents"] == 100_000, invoice["levied_amount_cents"]
        assert invoice["capped"] is False, (
            "a levy far below the ceiling is not a capped levy"
        )
        assert assessment["levied_amount_cents"] == 100_000, assessment["levied_amount_cents"]
        assert assessment["shortfall_cents"] == 0, assessment["shortfall_cents"]

    def test_two_invoices_accumulate_into_one_running_fee_total(self):
        """The invoice fee is the submitted `hours` multiplied by the engagement's
        `hourly_rate_cents`, rounded half up to whole cents. That fee is added to the engagement's
        `fees_accrued_cents` and the submitted `hours` are added to its `hours_logged`, after which the
        insolvency file's `administrative_expense_cents` is recomputed as the sum of
        `fees_accrued_cents` across every engagement on every claim of the file, in every engagement
        status. Accrued vendor fees are class 1 in the distribution waterfall and therefore rank ahead
        of claimants, but they never reduce any claim's `net_payable_cents`: administrative expense
        and covered loss are separate liabilities of the estate, not offsets against one another.

        Design: Corner/calculations/vendor_fee_accrual_running_total_across_two_invoices
        """
        env = setup_claim_under_adjustment(
            claim_overrides={
                "claim_number": "C-1",
                "claimant_name": "Ben Ortiz",
                "gross_loss_cents": 900_000,
            },
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )

        after_first = post_vendor_invoice(env, 4, "INV-1")
        assert after_first["fees_accrued_cents"] == 72_000, (
            f"4 hours at 18000 cents is 72000, got {after_first['fees_accrued_cents']}"
        )

        after_second = post_vendor_invoice(env, 6, "INV-2")
        assert after_second["fees_accrued_cents"] == 180_000, (
            f"a further 6 hours brings the running total to 180000, got "
            f"{after_second['fees_accrued_cents']}"
        )
        assert after_second["hours_logged"] == 10, after_second["hours_logged"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["administrative_expense_cents"] == 180_000, (
            insolvency["administrative_expense_cents"]
        )
        assert insolvency["administrative_paid_cents"] == 0, (
            f"accrual is not payment, got {insolvency['administrative_paid_cents']}"
        )

        claim = read_claim(env["claim"]["id"])
        assert claim["net_payable_cents"] == 890_000, (
            "administrative expense never offsets the covered loss, got "
            f"{claim['net_payable_cents']}"
        )


class TestWaterfallInputSetsAndBranches:
    """Which items a run may pay, and what happens when the cash is ample."""

    def test_a_run_pays_the_approved_claim_and_leaves_the_recommended_one_alone(self):
        """Class 2 comprises the covered claims of this insolvency file whose `status` is `APPROVED` or
        `PARTIALLY_PAID` — and only those; claims in `RECOMMENDED`, `REFERRED_OUT` or
        `DENIED_NOT_COVERED` are excluded, and a claim already in `PAID` has nothing outstanding.

        Design: Corner/calculations/distribution_ignores_recommended_claims_and_pays_only_approved_ones
        """
        env = setup_approved_claim(
            recommended_amount_cents=890_000,
            claim_overrides={
                "claim_number": "C-1",
                "claimant_name": "Ben Ortiz",
                "gross_loss_cents": 900_000,
            },
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        approved_claim = env["claim"]
        assert approved_claim["status"] == "APPROVED", approved_claim["status"]
        assert approved_claim["net_payable_cents"] == 890_000, approved_claim["net_payable_cents"]

        env["claim"] = _present(
            env, env["policy"], claim_number="C-2", claimant_name="Cora Diaz",
            loss_date="2026-01-20", gross_loss_cents=500_000,
        )
        screen_claim(env)
        engage_vendor(env, **KESTREL_ADJUSTER)
        recommended_claim = recommend(env, 490_000)
        assert recommended_claim["status"] == "RECOMMENDED", recommended_claim["status"]
        assert recommended_claim["net_payable_cents"] == 490_000, (
            recommended_claim["net_payable_cents"]
        )

        remit_estate_cash(env["insolvency"]["id"], 1_000_000, "EA-1")
        run = run_distribution(env["insolvency"]["id"], 1_000_000)

        assert run["class1_paid_cents"] == 0, run["class1_paid_cents"]
        assert run["class2_paid_cents"] == 890_000, (
            "only the approved claim is in the class 2 input set, got "
            f"{run['class2_paid_cents']}"
        )
        assert run["class3_paid_cents"] == 0, run["class3_paid_cents"]
        assert run["estate_undistributed_cents"] == 110_000, (
            "the cash the recommended claim did not receive stays in hand, got "
            f"{run['estate_undistributed_cents']}"
        )

        settled = read_claim(approved_claim["id"])
        assert settled["status"] == "PAID", settled["status"]
        assert settled["paid_amount_cents"] == 890_000, settled["paid_amount_cents"]

        untouched = read_claim(recommended_claim["id"])
        assert untouched["status"] == "RECOMMENDED", untouched["status"]
        assert untouched["paid_amount_cents"] == 0, untouched["paid_amount_cents"]

        assert read_insolvency(env["insolvency"]["id"])["reserved_claim_cents"] == 0

    def test_ample_funds_pay_both_refunds_outright_with_no_pro_rata_step(self):
        """When the funds reaching the class are greater than or equal to the total outstanding across
        all its items, every item is paid its full outstanding amount, the surplus flows on to the next
        class, and no rounding step occurs at all.

        Design: Corner/calculations/ample_funds_pay_every_class_three_refund_in_full
        """
        env = setup_two_policies_with_pending_refunds(
            refund_method="PRO_RATA",
            first_policy_overrides=dict(LIVE_TERM),
            second_policy_overrides={
                "policy_number": "PA-1002",
                "policyholder_name": "Boris Ilic",
                "effective_date": "2025-10-01",
                "expiration_date": "2026-10-01",
                "annual_premium_cents": 365_000,
            },
            remitted_cents=800_000,
        )
        first = env["first_refund"]
        second = env["second_refund"]
        assert_unearned_premium_refund(first)
        assert first["computed_refund_cents"] == 604_932, first["computed_refund_cents"]
        assert second["computed_refund_cents"] == 184_000, second["computed_refund_cents"]

        run = run_distribution(env["insolvency"]["id"], 800_000)

        assert run["class3_paid_cents"] == 788_932, (
            f"both refunds are paid in full, got {run['class3_paid_cents']}"
        )
        assert run["estate_undistributed_cents"] == 11_068, (
            f"800000 less the 788932 class 3 total, got {run['estate_undistributed_cents']}"
        )

        paid_first = read_premium_refund(env["policy"]["id"])
        assert paid_first["paid_amount_cents"] == 604_932, paid_first["paid_amount_cents"]
        assert paid_first["status"] == "PAID", paid_first["status"]

        paid_second = read_premium_refund(env["second_policy"]["id"])
        assert paid_second["paid_amount_cents"] == 184_000, paid_second["paid_amount_cents"]
        assert paid_second["status"] == "PAID", paid_second["status"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["pending_up_liability_cents"] == 0, (
            insolvency["pending_up_liability_cents"]
        )
        assert insolvency["estate_distributed_cents"] == 788_932, (
            insolvency["estate_distributed_cents"]
        )

    def test_approval_prices_the_claim_on_the_recovery_reported_after_screening(self):
        """The statutory net payable computation is re-run, so that any other-insurance recovery
        reported since screening is reflected in `net_payable_cents`, `alt_net_payable_cents` and
        `cap_binding`. The resulting `net_payable_cents` is added into the insolvency file's
        `reserved_claim_cents`, which is where the association's hard claim liability now lives.

        Design: Corner/calculations/approval_reconciles_the_payable_after_a_late_carrier_recovery
        """
        env = setup_screened_claim(
            claim_overrides={
                "claim_number": "C-1",
                "claimant_name": "Ben Ortiz",
                "gross_loss_cents": 2_000_000,
            },
            policy_overrides=dict(LIVE_TERM),
        )
        assert env["claim"]["net_payable_cents"] == 1_990_000, (
            f"the 2000000 loss less the 10000 deductible, got "
            f"{env['claim']['net_payable_cents']}"
        )

        layer = register_other_insurance(
            env,
            carrier_name="Northern Shield Indemnity",
            policy_number="NS-77",
            coverage_type="PRIMARY",
            stated_limit_cents=1_500_000,
        )
        advance_other_insurance(env, layer["id"], "PURSUING")
        resolved = advance_other_insurance(env, layer["id"], "EXHAUSTED", 1_200_000)
        assert resolved["status"] == "EXHAUSTED", resolved["status"]
        assert resolved["recovered_cents"] == 1_200_000, resolved["recovered_cents"]

        after_recovery = read_claim(env["claim"]["id"])
        assert after_recovery["net_payable_cents"] == 790_000, (
            "the recovery is offset the moment the layer resolves, got "
            f"{after_recovery['net_payable_cents']}"
        )

        engage_vendor(env, **KESTREL_ADJUSTER)
        recommend(env, 700_000)
        approved = approve(env)

        assert approved["status"] == "APPROVED", approved["status"]
        assert approved["net_payable_cents"] == 790_000, (
            "approval books the statutory figure, not the recommended one, got "
            f"{approved['net_payable_cents']}"
        )
        assert approved["recommended_amount_cents"] == 700_000, (
            approved["recommended_amount_cents"]
        )
        assert read_insolvency(env["insolvency"]["id"])["reserved_claim_cents"] == 790_000
