"""The distribution waterfall, the cascades it fires and the ledger identities it preserves."""

from test_helpers import (
    assert_claim_reserve_identity,
    assert_estate_ledger_identity,
    assert_insolvency,
    close_insolvency,
    read_claim,
    read_insolvency,
    read_vendor_assignment,
    run_distribution,
    setup_approved_claim_with_estate_cash,
    setup_approved_claim_with_vendor_invoice,
)

LARGE_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 4_500_000,
}
SMALL_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
KESTREL_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 2_500_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
NO_INVOICE_ADJUSTER = dict(KESTREL_ADJUSTER, settlement_authority_cents=2_500_000)


class TestDistributionRunCascade:
    """One run pays class 1 and class 2, retires the claim and closes its engagement."""

    def _funded_estate(self) -> dict:
        """Approved 3000000 claim plus 180000 of accrued adjuster fees, 3200000 in hand."""
        env = setup_approved_claim_with_vendor_invoice(
            hours=10,
            recommended_amount_cents=2_400_000,
            remitted_cents=3_200_000,
            claim_overrides=dict(LARGE_LOSS_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 3_000_000, insolvency["reserved_claim_cents"]
        assert insolvency["administrative_expense_cents"] == 180_000, (
            "10 hours at 18000 cents accrue as administrative expense, got "
            f"{insolvency['administrative_expense_cents']}"
        )
        env["insolvency"] = insolvency
        return env

    def test_the_run_pays_administrative_expense_before_the_claimant(self):
        """The supplied amount is the funds entering the waterfall, and the waterfall pays three
        classes strictly in order: class 1 is association administrative expense, class 2 is covered
        claim payments, and class 3 is unearned premium refunds.

        Class 1 is a single figure rather than a list of items: the outstanding administrative expense
        is the file's `administrative_expense_cents` less its `administrative_paid_cents`, and class 1
        is paid whichever is smaller of the available funds and that outstanding figure.

        Design: Difficulty/transitive_cascade/distribution_run_cascades_through_claim_into_vendor_engagement_and_ledger
        """
        env = self._funded_estate()
        run = run_distribution(env["insolvency"]["id"], 3_180_000)

        assert run["class1_paid_cents"] == 180_000, (
            f"class 1 takes the whole accrued fee first, got {run['class1_paid_cents']}"
        )
        assert run["class2_paid_cents"] == 3_000_000, (
            f"the remaining funds retire the claim in full, got {run['class2_paid_cents']}"
        )
        assert run["class3_paid_cents"] == 0, (
            f"no refund was filed, so class 3 is empty, got {run['class3_paid_cents']}"
        )
        assert run["distribution_sequence"] == 1, run["distribution_sequence"]

    def test_the_run_retires_the_claim_and_closes_its_live_engagement(self):
        """A covered claim in `APPROVED` that receives exactly its outstanding figure moves
        `APPROVED → PAID` with `paid_amount_cents` set equal to `net_payable_cents`, and a claim
        already in `PARTIALLY_PAID` that receives exactly its remaining outstanding figure moves
        `PARTIALLY_PAID → PAID` the same way. Any claim transition into `PAID` additionally closes
        every vendor engagement on that claim still in `ASSIGNED`.

        Design: Difficulty/transitive_cascade/distribution_run_cascades_through_claim_into_vendor_engagement_and_ledger
        """
        env = self._funded_estate()
        run_distribution(env["insolvency"]["id"], 3_180_000)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "PAID", claim["status"]
        assert claim["paid_amount_cents"] == 3_000_000, claim["paid_amount_cents"]

        assignment = read_vendor_assignment(claim["id"], env["assignment"]["id"])
        assert assignment["status"] == "CLOSED", (
            f"the paid claim closes its live engagement, got {assignment['status']}"
        )
        assert assignment["fees_accrued_cents"] == 180_000, (
            f"closure freezes the accrued fee, it does not erase it, got "
            f"{assignment['fees_accrued_cents']}"
        )

    def test_the_run_recomputes_the_whole_estate_ledger(self):
        """In every case the allocated amount is subtracted from the insolvency file's
        `reserved_claim_cents` and added to its `estate_distributed_cents`, so the reserve unwinds
        exactly as the cash goes out.

        At the end of the run the file's `estate_distributed_cents` has grown by the class 1 payment
        plus everything paid in classes 2 and 3, `estate_undistributed_cents` has been recomputed from
        the closed-ledger identity, `distribution_sequence` has been incremented by one, and the
        file's `version` has been incremented by one.

        Design: Difficulty/transitive_cascade/distribution_run_cascades_through_claim_into_vendor_engagement_and_ledger
        """
        env = self._funded_estate()
        run_distribution(env["insolvency"]["id"], 3_180_000)

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert_insolvency(insolvency)
        assert insolvency["reserved_claim_cents"] == 0, (
            f"the reserve unwinds as the cash goes out, got {insolvency['reserved_claim_cents']}"
        )
        assert insolvency["administrative_paid_cents"] == 180_000, (
            f"class 1 payments bank as administrative_paid_cents, got "
            f"{insolvency['administrative_paid_cents']}"
        )
        assert insolvency["estate_distributed_cents"] == 3_180_000, (
            insolvency["estate_distributed_cents"]
        )
        assert insolvency["estate_undistributed_cents"] == 20_000, (
            "the 3200000 remitted less the 3180000 distributed stays in hand, got "
            f"{insolvency['estate_undistributed_cents']}"
        )
        assert_estate_ledger_identity(insolvency)


class TestEstateLedgerIdentityAcrossTheWholeFile:
    """Remitted cash always equals distributed plus undistributed plus returned."""

    def _remitted_estate(self) -> dict:
        env = setup_approved_claim_with_estate_cash(
            remitted_cents=1_000_000,
            recommended_amount_cents=890_000,
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER, settlement_authority_cents=900_000),
        )
        env["insolvency"] = read_insolvency(env["insolvency"]["id"])
        return env

    def test_the_identity_holds_the_moment_the_receiver_remits(self):
        """A `ReceiverLiaison` records each early-access payment or dividend by supplying
        `amount_cents` and a `remittance_ref`; the amount is added to `estate_remitted_cents`,
        `estate_undistributed_cents` is recomputed from the closed-ledger identity rather than
        incremented, and the insolvency file's `version` is incremented by one — which is precisely
        why a distribution run planned against a pre-remittance view of the file will be turned away
        as stale.

        Design: Difficulty/compensating_invariant/estate_ledger_identity_holds_across_remittance_distribution_and_closure
        """
        env = self._remitted_estate()
        insolvency = env["insolvency"]

        assert insolvency["estate_remitted_cents"] == 1_000_000, (
            insolvency["estate_remitted_cents"]
        )
        assert insolvency["estate_distributed_cents"] == 0
        assert insolvency["estate_undistributed_cents"] == 1_000_000, (
            insolvency["estate_undistributed_cents"]
        )
        assert insolvency["estate_returned_cents"] == 0
        assert_estate_ledger_identity(insolvency)

    def test_the_identity_holds_after_the_distribution_run(self):
        """At the end of the run the file's `estate_distributed_cents` has grown by the class 1
        payment plus everything paid in classes 2 and 3, `estate_undistributed_cents` has been
        recomputed from the closed-ledger identity, `distribution_sequence` has been incremented by
        one, and the file's `version` has been incremented by one.

        Design: Difficulty/compensating_invariant/estate_ledger_identity_holds_across_remittance_distribution_and_closure
        """
        env = self._remitted_estate()
        run = run_distribution(env["insolvency"]["id"], 890_000)

        assert run["estate_undistributed_cents"] == 110_000, (
            f"1000000 in hand less the 890000 just paid out, got "
            f"{run['estate_undistributed_cents']}"
        )
        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "PAID", claim["status"]
        assert claim["paid_amount_cents"] == 890_000, claim["paid_amount_cents"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["estate_distributed_cents"] == 890_000
        assert insolvency["estate_returned_cents"] == 0
        assert_estate_ledger_identity(insolvency)

    def test_closure_moves_the_residue_into_returned_without_creating_a_cent(self):
        """When both checks clear, the file moves `TRIGGERED → CLOSED`, the whole of
        `estate_undistributed_cents` is added into `estate_returned_cents` and
        `estate_undistributed_cents` is set to 0 — which preserves the closed-ledger identity exactly,
        since the cash has merely changed bucket — and the file's `version` is incremented by one.

        Design: Difficulty/compensating_invariant/estate_ledger_identity_holds_across_remittance_distribution_and_closure
        """
        env = self._remitted_estate()
        run_distribution(env["insolvency"]["id"], 890_000)
        closed = close_insolvency(env["insolvency"]["id"])

        assert closed["status"] == "CLOSED", closed["status"]
        assert closed["estate_remitted_cents"] == 1_000_000
        assert closed["estate_distributed_cents"] == 890_000
        assert closed["estate_undistributed_cents"] == 0, (
            f"closure empties the undistributed bucket, got {closed['estate_undistributed_cents']}"
        )
        assert closed["estate_returned_cents"] == 110_000, (
            f"the residue goes back to the receiver, got {closed['estate_returned_cents']}"
        )
        assert closed["reserved_claim_cents"] == 0
        assert_estate_ledger_identity(closed)


class TestClaimReserveAndPaymentsCompensate:
    """Across successive runs the reserve and the payments stay pinned to the payable."""

    def _approved_claim_with_full_funding(self) -> dict:
        env = setup_approved_claim_with_estate_cash(
            remitted_cents=3_000_000,
            recommended_amount_cents=2_400_000,
            claim_overrides=dict(LARGE_LOSS_CLAIM),
            assignment_overrides=dict(NO_INVOICE_ADJUSTER),
        )
        env["insolvency"] = read_insolvency(env["insolvency"]["id"])
        return env

    def test_a_partial_run_splits_the_payable_between_reserve_and_payments(self):
        """A covered claim in `APPROVED` that receives a positive amount strictly less than its
        outstanding figure moves `APPROVED → PARTIALLY_PAID` with the allocated amount added to its
        `paid_amount_cents`.

        Design: Difficulty/compensating_invariant/claim_reserve_and_payments_always_sum_to_the_net_payable
        """
        env = self._approved_claim_with_full_funding()
        insolvency = env["insolvency"]
        assert insolvency["reserved_claim_cents"] == 3_000_000, insolvency["reserved_claim_cents"]

        run = run_distribution(insolvency["id"], 1_000_000)
        assert run["class2_paid_cents"] == 1_000_000, run["class2_paid_cents"]

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "PARTIALLY_PAID", claim["status"]
        assert claim["paid_amount_cents"] == 1_000_000, claim["paid_amount_cents"]
        assert claim["net_payable_cents"] == 3_000_000, claim["net_payable_cents"]
        assert_claim_reserve_identity(claim)

        after = read_insolvency(insolvency["id"])
        assert after["reserved_claim_cents"] == 2_000_000, (
            "the reserve falls by exactly what the claimant received, got "
            f"{after['reserved_claim_cents']}"
        )
        assert after["reserved_claim_cents"] + claim["paid_amount_cents"] == 3_000_000

    def test_the_engagement_only_closes_on_the_run_that_reaches_paid(self):
        """An engagement also closes automatically. Any claim transition into `DENIED_NOT_COVERED`,
        `REFERRED_OUT` or `PAID` moves every engagement on that claim whose `status` is `ASSIGNED` to
        `ASSIGNED → CLOSED`, freezing `fees_accrued_cents` while leaving the accrued total in the
        insolvency file's `administrative_expense_cents` — the work was done and the estate owes for
        it even though the claim itself is finished.

        Design: Difficulty/compensating_invariant/claim_reserve_and_payments_always_sum_to_the_net_payable
        """
        env = self._approved_claim_with_full_funding()
        run_distribution(env["insolvency"]["id"], 1_000_000)

        mid_assignment = read_vendor_assignment(env["claim"]["id"], env["assignment"]["id"])
        assert mid_assignment["status"] == "ASSIGNED", (
            f"a partially paid claim keeps its adjuster, got {mid_assignment['status']}"
        )

        run_distribution(env["insolvency"]["id"], 2_000_000)
        final_assignment = read_vendor_assignment(env["claim"]["id"], env["assignment"]["id"])
        assert final_assignment["status"] == "CLOSED", final_assignment["status"]

    def test_the_closing_run_leaves_the_reserve_empty_and_the_payable_intact(self):
        """In every case the allocated amount is subtracted from the insolvency file's
        `reserved_claim_cents` and added to its `estate_distributed_cents`, so the reserve unwinds
        exactly as the cash goes out. `PAID` is terminal for a claim.

        Design: Difficulty/compensating_invariant/claim_reserve_and_payments_always_sum_to_the_net_payable
        """
        env = self._approved_claim_with_full_funding()
        first = run_distribution(env["insolvency"]["id"], 1_000_000)
        second = run_distribution(env["insolvency"]["id"], 2_000_000)

        assert first["class2_paid_cents"] == 1_000_000
        assert second["class2_paid_cents"] == 2_000_000, second["class2_paid_cents"]
        assert second["distribution_sequence"] == 2, second["distribution_sequence"]

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "PAID", claim["status"]
        assert claim["paid_amount_cents"] == 3_000_000, claim["paid_amount_cents"]
        assert claim["net_payable_cents"] == 3_000_000, claim["net_payable_cents"]
        assert_claim_reserve_identity(claim)

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, insolvency["reserved_claim_cents"]
        assert insolvency["estate_distributed_cents"] == 3_000_000
        assert insolvency["estate_undistributed_cents"] == 0
        assert_estate_ledger_identity(insolvency)
