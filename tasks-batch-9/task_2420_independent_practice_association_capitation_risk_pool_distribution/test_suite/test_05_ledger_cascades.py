"""The five-level posting cascade and the four-level claim payment cascade."""

from test_helpers import (
    assert_fields,
    build_approved_claim,
    build_prorated_july_roster,
    build_single_member_funded_pool,
    pay_claim_state,
    post_file,
    read_agreement,
    read_enrollee,
    read_physician,
    read_pool,
    read_remittance,
    reconcile_file,
    sole_remittance,
)


def _july_roster_with_a_paid_professional_claim(api):
    """The three-member July roster, one paid claim, file still awaiting posting."""
    built = build_prorated_july_roster(api, with_pools=True, stop_at="PARSED")
    claim = build_approved_claim(
        api,
        built["agreement"]["id"],
        built["enrollees"][0]["id"],
        built["physician"]["id"],
        46000,
        service_date="2026-05-20T00:00:00Z",
    )
    pay_claim_state(api, claim["id"])

    reconcile_file(api, built["file"]["id"])
    built["remittance"] = sole_remittance(api, built["file"]["id"])
    built["claim"] = claim
    return built


class TestEnrollmentFilePostingCascade:
    def test_posting_marks_the_file_and_its_remittance_posted(self, api):
        """PRD §3.5: "At the first level the file's `status` becomes `POSTED` and
        its `RECONCILED` remittance moves to `POSTED`, advancing that
        remittance's `version` by 1."

        Design: Difficulty/transitive_cascade/enrollment_file_post_funding_cascade_depth_five
        """
        built = _july_roster_with_a_paid_professional_claim(api)
        assert built["remittance"]["status"] == "RECONCILED"

        posted = post_file(api, built["file"]["id"])
        assert posted["status"] == "POSTED"
        assert read_remittance(api, built["remittance"]["id"])["status"] == "POSTED"

    def test_posting_routes_the_money_into_both_pools_and_the_withhold_balance(
        self, api
    ):
        """PRD §3.5: "At the second level, because that remittance became
        `POSTED`, the money is routed: each risk pool of the agreement whose
        incurral period contains the first instant of the remittance's
        `coverage_month` is funded, with a `PROFESSIONAL` pool's `funded_cents`
        increasing by the remittance's `professional_allocation_cents`, an
        `INSTITUTIONAL` pool's `funded_cents` increasing by the remittance's
        `institutional_allocation_cents`, and both pools' `member_months_bps`
        increasing by the remittance's `member_month_count_bps`; at the same
        level the agreement's `withheld_balance_cents` increases by the
        remittance's `withhold_cents`."

        Design: Difficulty/transitive_cascade/enrollment_file_post_funding_cascade_depth_five
        """
        built = _july_roster_with_a_paid_professional_claim(api)
        professional_id = built["pools"]["PROFESSIONAL"]["id"]
        institutional_id = built["pools"]["INSTITUTIONAL"]["id"]
        assert read_pool(api, professional_id)["funded_cents"] == 0

        post_file(api, built["file"]["id"])

        assert_fields(
            read_pool(api, professional_id),
            {"funded_cents": 48142, "member_months_bps": 18387},
        )
        assert_fields(
            read_pool(api, institutional_id),
            {"funded_cents": 32094, "member_months_bps": 18387},
        )
        assert (
            read_agreement(api, built["agreement"]["id"])["withheld_balance_cents"]
            == 6039
        )

    def test_reconciliation_accrued_the_expected_capitation_before_posting(self, api):
        """PRD §3.5: "Reconciliation closes by accruing: the agreement's
        `accrued_capitation_cents` increases by the new remittance's
        `expected_capitation_cents` plus its `retro_adjustment_cents`."

        Design: Difficulty/transitive_cascade/enrollment_file_post_funding_cascade_depth_five
        """
        built = _july_roster_with_a_paid_professional_claim(api)
        assert read_agreement(api, built["agreement"]["id"])[
            "accrued_capitation_cents"
        ] == 86275

        post_file(api, built["file"]["id"])
        assert read_agreement(api, built["agreement"]["id"])[
            "accrued_capitation_cents"
        ] == 86275

    def test_funding_recomputes_the_loss_ratio_and_the_deficit_flag(self, api):
        """PRD §3.5: "At the third level, because each funded pool's
        `funded_cents` changed, that pool's `loss_ratio_bps` is recomputed and
        its `deficit_flag` re-evaluated."

        Design: Difficulty/transitive_cascade/enrollment_file_post_funding_cascade_depth_five
        """
        built = _july_roster_with_a_paid_professional_claim(api)
        professional_id = built["pools"]["PROFESSIONAL"]["id"]
        institutional_id = built["pools"]["INSTITUTIONAL"]["id"]

        assert_fields(
            read_pool(api, professional_id), {"loss_ratio_bps": 0, "deficit_flag": False}
        )

        post_file(api, built["file"]["id"])

        assert_fields(
            read_pool(api, professional_id),
            {"loss_ratio_bps": 9555, "deficit_flag": True},
        )
        assert_fields(
            read_pool(api, institutional_id),
            {"loss_ratio_bps": 0, "deficit_flag": False},
        )

    def test_the_deficit_moves_the_posture_and_closes_every_open_panel(self, api):
        """PRD §3.5: "At the fourth level, if any pool's `deficit_flag` has become
        true, the agreement's `capitation_posture` is re-derived to
        `UNDER_REVIEW`. At the fifth level, because the posture has left
        `CURRENT`, every physician of the agreement whose `panel_status` is
        `OPEN` is set to `CLOSED_TO_NEW`."

        Design: Difficulty/transitive_cascade/enrollment_file_post_funding_cascade_depth_five
        """
        built = _july_roster_with_a_paid_professional_claim(api)
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "CURRENT"
        )
        assert read_physician(api, built["physician"]["id"])["panel_status"] == "OPEN"

        post_file(api, built["file"]["id"])

        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "UNDER_REVIEW"
        )
        assert (
            read_physician(api, built["physician"]["id"])["panel_status"]
            == "CLOSED_TO_NEW"
        )


def _funded_pool_with_an_approved_claim(api):
    built = build_single_member_funded_pool(
        api, base_pmpm_cents=20000, stop_loss_attachment_cents=10000
    )
    built["claim"] = build_approved_claim(
        api,
        built["agreement"]["id"],
        built["enrollee"]["id"],
        built["physician"]["id"],
        20000,
        service_date="2026-06-15T00:00:00Z",
    )
    return built


class TestClaimPaymentLedgerCascade:
    def test_payment_sets_paid_cents_and_moves_the_pool_paid_ledger(self, api):
        """PRD §3.6: "Second, because `paid_cents` was set, the pool's
        `paid_claims_cents` increases by that amount and the pool's
        `loss_ratio_bps` is recomputed per the definition in §3.5."

        Design: Difficulty/transitive_cascade/claim_payment_ledger_cascade_depth_four
        """
        built = _funded_pool_with_an_approved_claim(api)
        before = read_pool(api, built["pool"]["id"])
        assert_fields(before, {"funded_cents": 20000, "paid_claims_cents": 0})

        paid = pay_claim_state(api, built["claim"]["id"])
        assert_fields(paid, {"status": "PAID", "paid_cents": 20000})
        assert read_pool(api, built["pool"]["id"])["paid_claims_cents"] == 20000

    def test_payment_raises_the_enrollee_total_and_the_stop_loss_eligible_count(
        self, api
    ):
        """PRD §3.6: "Third, because the pool's paid ledger moved, the enrollee's
        `cumulative_paid_claims_cents` increases by the same amount, and when
        that enrollee's paid total within this pool comes to strictly exceed the
        agreement's `stop_loss_attachment_cents` for the first time, the pool's
        `stop_loss_eligible_enrollee_count` increases by 1."

        Design: Difficulty/transitive_cascade/claim_payment_ledger_cascade_depth_four
        """
        built = _funded_pool_with_an_approved_claim(api)
        assert (
            read_pool(api, built["pool"]["id"])["stop_loss_eligible_enrollee_count"] == 0
        )

        pay_claim_state(api, built["claim"]["id"])

        assert (
            read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"]
            == 20000
        )
        assert (
            read_pool(api, built["pool"]["id"])["stop_loss_eligible_enrollee_count"] == 1
        )

    def test_payment_flips_the_deficit_flag_and_the_capitation_posture(self, api):
        """PRD §3.6: "Fourth, because `loss_ratio_bps` changed, `deficit_flag` is
        re-evaluated as strictly greater than 9500 basis points, and when it
        becomes true the agreement's `capitation_posture` is re-derived to
        `UNDER_REVIEW` — which, per §2.9, closes every `OPEN` panel of that
        agreement."

        Design: Difficulty/transitive_cascade/claim_payment_ledger_cascade_depth_four
        """
        built = _funded_pool_with_an_approved_claim(api)
        assert read_pool(api, built["pool"]["id"])["deficit_flag"] is False
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "CURRENT"
        )

        pay_claim_state(api, built["claim"]["id"])

        assert_fields(
            read_pool(api, built["pool"]["id"]),
            {"loss_ratio_bps": 10000, "deficit_flag": True},
        )
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "UNDER_REVIEW"
        )
