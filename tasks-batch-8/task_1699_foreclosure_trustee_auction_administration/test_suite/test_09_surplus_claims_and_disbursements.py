"""Surplus waterfall variants, claims administration, and disbursement reversal."""
from test_helpers import (
    ADMIN,
    CM,
    CM_FILER,
    CM_REVIEWER,
    ApiErrorId,
    approve_claim,
    file_claim,
    get_case,
    make_case_manager_headers,
    set_clock,
    setup_case_at_nots_recorded,
    setup_closed_sale,
    trustee_fee_disbursement,
    validate_error,
    validate_paginated,
    validate_success,
)


def _closed_sale_with_surplus(api, reference_code, loan_reference, venue,
                              distribution_method):
    """Third-party win at 43000000 on standard terms -> surplus 1640950."""
    return setup_closed_sale(
        reference_code, venue_name=venue, loan_reference=loan_reference,
        opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
        strategy="UP_TO_MAX", bid_amount_cents=43_000_000,
        distribution_method=distribution_method,
    )


def _file_and_approve_three_claims(api, case_id):
    """Claims A/B tier 1 (2000000, 1000000) and C tier 2 (900000), all approved
    at the claimed amount. Filed by one case manager, reviewed by another."""
    set_clock("2026-12-01T00:00:00Z")
    a = file_claim(case_id, claimant_name="Lien A", priority_rank=1,
                   claimed_amount_cents=2_000_000)
    b = file_claim(case_id, claimant_name="Lien B", priority_rank=1,
                   claimed_amount_cents=1_000_000)
    c = file_claim(case_id, claimant_name="Creditor C",
                   claimant_type="JUDGMENT_CREDITOR", priority_rank=2,
                   claimed_amount_cents=900_000)
    approve_claim(a["id"], 2_000_000)
    approve_claim(b["id"], 1_000_000)
    approve_claim(c["id"], 900_000)
    return {"A": a, "B": b, "C": c}


def _claim_row(api, case_id, claim_id):
    rows, _meta = validate_paginated(api.list_surplus_claims(case_id, CM))
    return next(r for r in rows if r["id"] == claim_id)


def _claim_disbursement(api, claim_id):
    rows, _meta = validate_paginated(
        api.list_disbursements(CM, params={"surplus_claim_id": claim_id})
    )
    assert len(rows) == 1
    return rows[0]


class TestSurplusWaterfallVariants:
    def test_statutory_priority_pays_in_filing_order(self, api):
        """PRD §3.9: "Under `STATUTORY_PRIORITY`, claims within the tier are paid in strict filing order — earliest `created_at` first, never ordered by record identifier — each receiving the lesser of its unpaid approved amount and the remaining surplus. An early large claim can starve later same-tier claims entirely."
        PRD §3.8: "The surplus is what remains: the `winning_bid_cents` minus the total obligations — the trustee fee, the sum of the approved advances, and the total debt at close — floored at zero when the bid does not cover the obligations. The case's `undistributed_surplus_cents` is set to that surplus."

        Design: Difficulty/dual_variant_calc/surplus_waterfall_statutory_vs_prorata
        """
        ctx = _closed_sale_with_surplus(api, "BEN-W1S", "LN-W1S", "VEN-W1",
                                        "STATUTORY_PRIORITY")
        case_id = ctx["case"]["id"]
        claims = _file_and_approve_three_claims(api, case_id)
        run = validate_success(api.distribute_surplus(case_id, CM), 200)

        a = _claim_row(api, case_id, claims["A"]["id"])
        b = _claim_row(api, case_id, claims["B"]["id"])
        c = _claim_row(api, case_id, claims["C"]["id"])
        assert a["paid_cents"] == 1_640_950, (
            f"the early large claim draws the whole 1640950 pool, got {a['paid_cents']}"
        )
        assert a["status"] == "APPROVED", "partially paid remains APPROVED"
        assert b["paid_cents"] == 0
        assert c["paid_cents"] == 0
        disb = _claim_disbursement(api, claims["A"]["id"])
        assert disb["amount_cents"] == 1_640_950
        assert disb["recipient_type"] == "CLAIMANT"
        assert get_case(case_id)["undistributed_surplus_cents"] == 0
        assert run["undistributed_surplus_cents"] == 0

    def test_pro_rata_splits_tier_pool_with_cent_remainder(self, api):
        """PRD §3.9: "Under `PRO_RATA`, claims within the tier split the tier pool proportionally: each claim's share is the tier pool multiplied by the claim's unpaid approved amount and divided by the tier's total unpaid approved amount, rounded down to whole cents. The leftover cents — always fewer than the number of claims in the tier — are then distributed one cent at a time in `created_at` ascending order until exhausted. Identical inputs yield different per-claim payouts under the two variants."

        Design: Difficulty/dual_variant_calc/surplus_waterfall_statutory_vs_prorata
        """
        ctx = _closed_sale_with_surplus(api, "BEN-W1P", "LN-W1P", "VEN-W2",
                                        "PRO_RATA")
        case_id = ctx["case"]["id"]
        claims = _file_and_approve_three_claims(api, case_id)
        validate_success(api.distribute_surplus(case_id, CM), 200)

        a = _claim_row(api, case_id, claims["A"]["id"])
        b = _claim_row(api, case_id, claims["B"]["id"])
        c = _claim_row(api, case_id, claims["C"]["id"])
        # floor(1640950 * 2/3) == 1093966 plus the single remainder cent to the
        # earliest-filed claim; floor(1640950 * 1/3) == 546983.
        assert a["paid_cents"] == 1_093_967, (
            f"pro-rata share plus remainder cent, got {a['paid_cents']}"
        )
        assert b["paid_cents"] == 546_983
        assert c["paid_cents"] == 0
        assert _claim_disbursement(api, claims["A"]["id"])["amount_cents"] == 1_093_967
        assert _claim_disbursement(api, claims["B"]["id"])["amount_cents"] == 546_983
        assert get_case(case_id)["undistributed_surplus_cents"] == 0


class TestDisbursementReversalConservation:
    def _sold_case_with_one_claim_paid(self, api):
        ctx = _closed_sale_with_surplus(api, "BEN-K1", "LN-K1", "VEN-K1",
                                        "STATUTORY_PRIORITY")
        case_id = ctx["case"]["id"]
        set_clock("2026-12-01T00:00:00Z")
        claim = file_claim(case_id, claimant_name="Lien K",
                           claimed_amount_cents=2_000_000)
        approve_claim(claim["id"], 2_000_000)
        run1 = validate_success(api.distribute_surplus(case_id, CM), 200)
        disb = _claim_disbursement(api, claim["id"])
        assert disb["amount_cents"] == 1_640_950
        assert get_case(case_id)["undistributed_surplus_cents"] == 0
        return ctx, claim, run1, disb

    def test_reversal_restores_surplus_and_rolls_back_claim(self, api):
        """PRD §2.11: "The system maintains a funds-conservation invariant on every case whose sale has closed: the sum of `amount_cents` across that case's `CLEARED` disbursements of recipient type `CLAIMANT` or `BORROWER_RESIDUE`, plus the case's `undistributed_surplus_cents`, always equals the surplus computed at auction close. A disbursement paired with its reversal leaves this quantity unchanged, and the invariant is re-verified after every distribution run and every reversal."
        PRD §3.9: "Reversing a `CLAIMANT` disbursement reduces the linked claim's `paid_cents` by the amount, and if the claim's `paid_cents` thereby falls below its `approved_amount_cents`, the claim regresses from `PAID` back to `APPROVED`. Reversing a `CLAIMANT` or `BORROWER_RESIDUE` disbursement also restores the case's `undistributed_surplus_cents` by the amount."

        Design: Difficulty/compensating_invariant/disbursement_reversal_restores_surplus_conservation
        """
        ctx, claim, _run1, disb = self._sold_case_with_one_claim_paid(api)
        case_id = ctx["case"]["id"]
        reversed_d = validate_success(
            api.reverse_disbursement(
                disb["id"], {"reversal_reason": "claim documentation audit"}, ADMIN
            ),
            200,
        )
        assert reversed_d["status"] == "REVERSED"
        # Conservation: 0 CLEARED claimant cents + 1640950 undistributed == surplus.
        assert get_case(case_id)["undistributed_surplus_cents"] == 1_640_950
        row = _claim_row(api, case_id, claim["id"])
        assert row["paid_cents"] == 0
        assert row["status"] == "APPROVED"

    def test_redistribution_after_reversal_recreates_disbursement(self, api):
        """PRD §3.9: "Each run is numbered by a one-based `distribution_run_index` on every disbursement it creates, and the run's response summarizes the work: the `run_index`, the `created_disbursement_count`, the `distributed_cents` paid out, the remaining `undistributed_surplus_cents`, and the resulting `case_status`."
        PRD §2.11: "A disbursement paired with its reversal leaves this quantity unchanged, and the invariant is re-verified after every distribution run and every reversal."

        Design: Difficulty/compensating_invariant/disbursement_reversal_restores_surplus_conservation
        """
        ctx, claim, run1, disb = self._sold_case_with_one_claim_paid(api)
        case_id = ctx["case"]["id"]
        validate_success(
            api.reverse_disbursement(
                disb["id"], {"reversal_reason": "claim documentation audit"}, ADMIN
            ),
            200,
        )
        run2 = validate_success(api.distribute_surplus(case_id, CM), 200)
        assert run2["run_index"] == run1["run_index"] + 1
        rows, _meta = validate_paginated(
            api.list_disbursements(
                CM, params={"surplus_claim_id": claim["id"]}
            )
        )
        cleared = [d for d in rows if d["status"] == "CLEARED"]
        assert len(cleared) == 1
        assert cleared[0]["amount_cents"] == 1_640_950
        assert cleared[0]["recipient_type"] == "CLAIMANT"
        assert _claim_row(api, case_id, claim["id"])["paid_cents"] == 1_640_950
        assert get_case(case_id)["undistributed_surplus_cents"] == 0


class TestClaimAdministration:
    def test_segregation_of_duties_same_user_review_rejected(self, api):
        """PRD §2.1: "Segregation of duties is enforced where a single operator could otherwise control both sides of a decision. In particular, the case manager who reviews a surplus claim must not be the same user who filed it; a review where the reviewer's `X-User-ID` equals the claim's `filed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_user_review_rejected
        """
        ctx = setup_closed_sale("BEN-VL6", venue_name="VEN-VL6",
                                loan_reference="LN-VL6",
                                opening_bid_cents=42_000_000,
                                max_bid_cents=43_000_000,
                                strategy="OPENING_ONLY", bid_amount_cents=None)
        case_id = ctx["case"]["id"]
        set_clock("2026-12-01T00:00:00Z")
        claim = file_claim(case_id, claimant_name="SoD Lien",
                           claimed_amount_cents=100_000)
        filer = make_case_manager_headers("cm_filer_1")
        resp = api.review_surplus_claim(
            claim["id"],
            {"decision": "APPROVE", "approved_amount_cents": 100_000},
            filer,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        reviewed = validate_success(
            api.review_surplus_claim(
                claim["id"],
                {"decision": "APPROVE", "approved_amount_cents": 100_000},
                make_case_manager_headers("cm_reviewer_1"),
            ),
            200,
        )
        assert reviewed["status"] == "APPROVED"
        assert reviewed["approved_amount_cents"] == 100_000

    def test_claims_deadline_day180_boundary(self, api):
        """PRD §3.9: "The claims window is one hundred eighty days from the sale's close: the `filed_date` must equal the current clock date and must be no later than one hundred eighty days after the sale's `closed_at` — a filing exactly on the hundred-eightieth day is acceptable, and a filing past the deadline is rejected with `ERR_CLAIMS_DEADLINE_PASSED` (HTTP 422); the case-state check runs before the deadline check."

        Design: Corner/validations/claims_deadline_day180_boundary
        """
        ctx = setup_closed_sale("BEN-VL4", venue_name="VEN-VL4",
                                loan_reference="LN-VL4",
                                opening_bid_cents=42_000_000,
                                max_bid_cents=43_000_000,
                                strategy="OPENING_ONLY", bid_amount_cents=None)
        case_id = ctx["case"]["id"]
        # Close 2026-11-23 + 180 days == 2027-05-22.
        set_clock("2027-05-23T00:00:00Z")
        late = api.create_surplus_claim(
            case_id,
            {
                "claimant_name": "Late Lien",
                "claimant_type": "JUNIOR_LIENHOLDER",
                "priority_rank": 1,
                "claimed_amount_cents": 100_000,
                "filed_date": "2027-05-23",
            },
            CM_FILER,
        )
        validate_error(late, ApiErrorId.ERR_CLAIMS_DEADLINE_PASSED, 422)
        set_clock("2027-05-22T00:00:00Z")
        timely = validate_success(
            api.create_surplus_claim(
                case_id,
                {
                    "claimant_name": "Timely Lien",
                    "claimant_type": "JUNIOR_LIENHOLDER",
                    "priority_rank": 1,
                    "claimed_amount_cents": 100_000,
                    "filed_date": "2027-05-22",
                },
                CM_FILER,
            ),
            201,
        )
        assert timely["status"] == "FILED"

    def test_claim_review_after_deny_rejected(self, api):
        """PRD §3.9: "A `CaseManager` reviews a claim that is in `FILED` status — anything else is rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409) — and the reviewer's `X-User-ID` must differ from the claim's `filed_by_user_id`; a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES` before any decision is examined."

        Design: Corner/errors/claim_review_after_deny_rejected
        """
        ctx = setup_closed_sale("BEN-ER8", venue_name="VEN-ER8",
                                loan_reference="LN-ER8",
                                opening_bid_cents=42_000_000,
                                max_bid_cents=43_000_000,
                                strategy="OPENING_ONLY", bid_amount_cents=None)
        case_id = ctx["case"]["id"]
        set_clock("2026-12-01T00:00:00Z")
        claim = file_claim(case_id, claimant_name="Bad Doc Lien",
                           claimed_amount_cents=100_000)
        validate_success(
            api.review_surplus_claim(
                claim["id"],
                {"decision": "DENY", "denial_reason": "no recorded lien"},
                CM_REVIEWER,
            ),
            200,
        )
        resp = api.review_surplus_claim(
            claim["id"],
            {"decision": "APPROVE", "approved_amount_cents": 100_000},
            CM_REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_STATE, 409)


class TestDistributionGuards:
    def test_distribute_before_sale_rejected(self, api):
        """PRD §3.9: "A `CaseManager` invokes a distribution run against the case; a run with nothing to do — no `undistributed_surplus_cents`, no approved claims awaiting payment, and no borrower-residue work — is rejected with `ERR_NO_DISTRIBUTABLE_SURPLUS` (HTTP 422), and a run attempted before the case has been sold is rejected with `ERR_INVALID_CASE_STATE`."

        Design: Corner/endpoints/distribute_before_sale_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-E1", loan_reference="LN-E1")
        resp = api.distribute_surplus(ctx["case"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE, 409)

    def test_distribute_with_zero_surplus_rejected(self, api):
        """PRD §3.9: "A `CaseManager` invokes a distribution run against the case; a run with nothing to do — no `undistributed_surplus_cents`, no approved claims awaiting payment, and no borrower-residue work — is rejected with `ERR_NO_DISTRIBUTABLE_SURPLUS` (HTTP 422), and a run attempted before the case has been sold is rejected with `ERR_INVALID_CASE_STATE`."
        PRD §3.8: "The surplus is what remains: the `winning_bid_cents` minus the total obligations — the trustee fee, the sum of the approved advances, and the total debt at close — floored at zero when the bid does not cover the obligations. The case's `undistributed_surplus_cents` is set to that surplus."

        Design: Corner/errors/distribute_with_zero_surplus_rejected
        """
        # Beneficiary win at 41000000 against obligations 41349770 -> surplus 0.
        ctx = setup_closed_sale("BEN-ER3", venue_name="VEN-ER3",
                                loan_reference="LN-ER3",
                                opening_bid_cents=41_000_000,
                                max_bid_cents=41_000_000,
                                strategy="OPENING_ONLY", bid_amount_cents=None)
        case_id = ctx["case"]["id"]
        assert get_case(case_id)["undistributed_surplus_cents"] == 0
        resp = api.distribute_surplus(case_id, CM)
        validate_error(resp, ApiErrorId.ERR_NO_DISTRIBUTABLE_SURPLUS, 422)

    def test_reverse_reversed_disbursement_rejected(self, api):
        """PRD §3.9: "A `TrusteeAdmin` reverses a disbursement that is in `CLEARED` status — a disbursement in any other status is rejected with `ERR_INVALID_DISBURSEMENT_STATE` (HTTP 409) — by supplying a non-empty `reversal_reason`, and only while the case has not yet reached `CLOSED`, after which the books are final and an attempt surfaces `ERR_INVALID_CASE_STATE`."

        Design: Corner/errors/reverse_reversed_disbursement_rejected
        """
        ctx = setup_closed_sale("BEN-ER2", venue_name="VEN-ER2",
                                loan_reference="LN-ER2",
                                opening_bid_cents=42_000_000,
                                max_bid_cents=43_000_000,
                                strategy="OPENING_ONLY", bid_amount_cents=None)
        fee = trustee_fee_disbursement(ctx["case"]["id"])
        validate_success(
            api.reverse_disbursement(
                fee["id"], {"reversal_reason": "fee audit"}, ADMIN
            ),
            200,
        )
        resp = api.reverse_disbursement(
            fee["id"], {"reversal_reason": "second attempt"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DISBURSEMENT_STATE, 409)
