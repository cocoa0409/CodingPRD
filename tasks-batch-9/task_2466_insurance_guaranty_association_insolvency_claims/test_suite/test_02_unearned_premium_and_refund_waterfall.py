"""Unearned premium refunds on cancelled policies and how a short run splits them."""

from test_helpers import (
    assert_estate_ledger_identity,
    assert_unearned_premium_refund,
    read_insolvency,
    read_policy,
    read_premium_refund,
    run_distribution,
    setup_policy_with_premium_refund,
    setup_two_policies_with_pending_refunds,
)

PRO_RATA_CENTS = 604_932
SHORT_RATE_CENTS = 544_438

FIRST_POLICY = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "annual_premium_cents": 1_200_000,
}
SECOND_POLICY = {
    "policy_number": "PA-1002",
    "policyholder_name": "Boris Ilic",
    "annual_premium_cents": 365_000,
}


class TestRefundVariantsOnOneCancelledPolicy:
    """Both statutory variants are computed on every filing."""

    def test_short_rate_filing_applies_the_factor_before_the_single_rounding_step(self):
        """The short-rate raw figure is that same product and quotient —
        `annual_premium_cents` multiplied by `unexpired_days`, divided by the term length — then
        multiplied by a short-rate factor of nine tenths, and only then rounded half up to whole
        cents.

        Design: Difficulty/dual_variant_calc/unearned_premium_pro_rata_versus_short_rate_on_same_policy
        """
        env = setup_policy_with_premium_refund("SHORT_RATE", policy_overrides=dict(FIRST_POLICY))

        refund = env["refund"]
        assert_unearned_premium_refund(refund)
        assert refund["refund_method"] == "SHORT_RATE"
        assert refund["computed_refund_cents"] == SHORT_RATE_CENTS, (
            "1200000 cents over 184 of 365 days at nine tenths rounds once to 544438; rounding the "
            f"pro-rata figure first would have produced 544439, got {refund['computed_refund_cents']}"
        )
        assert refund["alt_refund_cents"] == PRO_RATA_CENTS, (
            f"the unelected pro-rata variant is 604932, got {refund['alt_refund_cents']}"
        )
        assert refund["status"] == "PENDING", refund["status"]
        assert refund["paid_amount_cents"] == 0

    def test_pro_rata_filing_swaps_which_figure_is_elected_and_snapshots_the_class(self):
        """Whichever variant `refund_method` names becomes the elected raw figure and the other
        becomes the alternative raw figure.

        Design: Difficulty/dual_variant_calc/unearned_premium_pro_rata_versus_short_rate_on_same_policy
        """
        env = setup_policy_with_premium_refund("PRO_RATA", policy_overrides=dict(FIRST_POLICY))

        refund = env["refund"]
        assert_unearned_premium_refund(refund)
        assert refund["computed_refund_cents"] == PRO_RATA_CENTS, (
            f"the elected pro-rata figure is 604932, got {refund['computed_refund_cents']}"
        )
        assert refund["alt_refund_cents"] == SHORT_RATE_CENTS, (
            f"the unelected short-rate figure is 544438, got {refund['alt_refund_cents']}"
        )
        assert refund["capped"] is False, (
            "604932 is well below the line's 1000000 unearned premium cap, so nothing was capped"
        )
        assert refund["priority_class"] == 2, (
            f"the line ranks its refunds in class 2, got {refund['priority_class']}"
        )

    def test_filing_reaches_back_into_the_policy_and_the_estate_exposure(self):
        """On the insolvency file, `computed_refund_cents` is added into
        `pending_up_liability_cents`, booking the association's refund exposure the moment it is
        quantified.

        Design: Difficulty/dual_variant_calc/unearned_premium_pro_rata_versus_short_rate_on_same_policy
        """
        env = setup_policy_with_premium_refund("SHORT_RATE", policy_overrides=dict(FIRST_POLICY))

        policy = read_policy(env["policy"]["id"])
        assert policy["unexpired_days"] == 184, (
            "cancellation on 2026-03-31 leaves 184 whole days to the 2026-10-01 expiration, got "
            f"{policy['unexpired_days']}"
        )
        assert policy["up_refund_filed"] is True
        assert policy["version"] > 1, "the filing bumps the policy version"

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["pending_up_liability_cents"] == SHORT_RATE_CENTS, (
            "the elected refund figure is booked as refund exposure, got "
            f"{insolvency['pending_up_liability_cents']}"
        )


class TestShortDistributionAcrossTwoRefunds:
    """A run that cannot cover class 3 in full settles it pro rata."""

    def _env(self) -> dict:
        return setup_two_policies_with_pending_refunds(
            refund_method="PRO_RATA",
            first_policy_overrides=dict(FIRST_POLICY),
            second_policy_overrides=dict(SECOND_POLICY),
            remitted_cents=500_000,
        )

    def test_residual_cent_of_the_pro_rata_split_goes_to_the_earliest_refund(self):
        """The residual — the available funds less the sum of the truncated shares — is then handed
        out one cent at a time, walking the items in that class's own declared ordering, until the
        residual is exhausted.

        Design: Difficulty/combinatorial_formula/waterfall_pro_rata_remainder_cent_goes_to_earliest_refund
        """
        env = self._env()
        report = run_distribution(env["insolvency"]["id"], 500_000)

        assert report["class3_paid_cents"] == 500_000, (
            f"the whole run lands in class 3, got {report['class3_paid_cents']}"
        )
        assert report["distribution_sequence"] == 1, report["distribution_sequence"]

        first = read_premium_refund(env["policy"]["id"])
        second = read_premium_refund(env["second_policy"]["id"])
        assert first["computed_refund_cents"] == PRO_RATA_CENTS
        assert second["computed_refund_cents"] == 184_000
        assert first["paid_amount_cents"] == 383_387, (
            "the truncated shares total 499999, and the single residual cent goes to the "
            f"earliest-created refund, got {first['paid_amount_cents']}"
        )
        assert second["paid_amount_cents"] == 116_613, (
            f"the later refund keeps its truncated share of 116613, got {second['paid_amount_cents']}"
        )
        assert first["paid_amount_cents"] + second["paid_amount_cents"] == 500_000

    def test_both_part_paid_refunds_move_off_pending_and_unwind_the_exposure(self):
        """In every case the allocated amount is subtracted from the insolvency file's
        `pending_up_liability_cents` and added to its `estate_distributed_cents`.

        Design: Difficulty/combinatorial_formula/waterfall_pro_rata_remainder_cent_goes_to_earliest_refund
        """
        env = self._env()
        run_distribution(env["insolvency"]["id"], 500_000)

        first = read_premium_refund(env["policy"]["id"])
        second = read_premium_refund(env["second_policy"]["id"])
        assert first["status"] == "PARTIALLY_PAID", first["status"]
        assert second["status"] == "PARTIALLY_PAID", second["status"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["estate_distributed_cents"] == 500_000
        assert insolvency["estate_undistributed_cents"] == 0
        assert insolvency["pending_up_liability_cents"] == 288_932, (
            "788932 of refund exposure less the 500000 paid out leaves 288932, got "
            f"{insolvency['pending_up_liability_cents']}"
        )
        assert_estate_ledger_identity(insolvency)

    def test_nothing_flows_onward_from_a_class_settled_pro_rata(self):
        """When the funds reaching the class are less than that total, the class is settled pro rata
        and nothing flows onward: each item's share is the available funds multiplied by that item's
        outstanding amount, divided by the class's total outstanding, truncated downward to whole
        cents.

        Design: Difficulty/combinatorial_formula/waterfall_pro_rata_remainder_cent_goes_to_earliest_refund
        """
        env = self._env()
        report = run_distribution(env["insolvency"]["id"], 500_000)

        assert report["class1_paid_cents"] == 0, (
            "no vendor engagement has invoiced, so class 1 is empty"
        )
        assert report["class2_paid_cents"] == 0, (
            "no claim has been approved, so class 2 is empty"
        )
        assert len(report["refund_payments"]) == 2, (
            f"both class 3 items must appear in the per-item detail, got {report['refund_payments']}"
        )
        assert report["estate_undistributed_cents"] == 0, (
            "class 3 absorbed every available cent, so nothing remains undistributed"
        )
