"""Expenditure truncation, high-cost claimant watch, and review cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    add_participant,
    adjudicate,
    build_period_scenario,
    create_period,
    determine_review,
    get_period,
    ingest_claim,
    list_reviews,
    lock_period,
    make_actuary_headers,
    make_review_officer_headers,
    open_period,
    run_alignment,
    void_claim,
    setup_canonical_proposed_settlement,
    validate_error,
    validate_paginated,
    validate_success,
)

ACTUARY = make_actuary_headers()


class TestTruncationBoundary:
    def _cap_boundary_period(self, tax_id):
        """B1 sums to exactly 20000000 (== cap); B2 sums to 20000001."""
        return build_period_scenario(
            tax_id=tax_id,
            beneficiaries=(
                {"medicare_id": "MBI-TR-1", "birth_year": 1980},
                {"medicare_id": "MBI-TR-2", "birth_year": 1981},
            ),
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 10000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 9000000, "claim_type": "PART_A"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-04-01",
                 "amount": 9000000, "claim_type": "PART_A"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-05-01",
                 "amount": 1990000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-02-01",
                 "amount": 10000, "claim_type": "PART_B"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-03-01",
                 "amount": 9000000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-04-01",
                 "amount": 9000000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-05-01",
                 "amount": 1990001, "claim_type": "PART_A"},
            ),
            benchmark_variant=None,
            quality_scores=None,
        )

    def test_beneficiary_at_exact_cap_is_not_truncated(self, api, actuary_headers):
        """PRD §3.6: "Per beneficiary, the summed allowed amounts are truncated at
        a cap of 20000000 cents — two hundred thousand dollars: a beneficiary
        whose sum exceeds the cap contributes exactly the cap, while a sum equal
        to the cap is **not** truncated."

        Design: Difficulty/boundary_precision_check/truncation_at_exact_cap_vs_one_cent_over
        """
        ctx = self._cap_boundary_period("ACO-TR")
        res = api.get_expenditure_summary(ctx["period"]["id"], actuary_headers)
        summary = validate_success(res, 200)
        assert summary["raw_adjudicated_total_cents"] == 40000001
        assert summary["truncated_total_cents"] == 40000000

    def test_beneficiary_one_cent_over_cap_truncated_by_one(self, api, actuary_headers):
        """PRD §3.6: "The aggregation reports five figures:
        `raw_adjudicated_total_cents` (the summed included claims before
        truncation), `truncated_total_cents` (the sum of per-beneficiary
        truncated totals), `truncated_away_cents` (raw minus truncated),
        `included_beneficiary_count` (beneficiaries with at least one included
        claim), and `excluded_claim_count` (`ADJUDICATED` claims filtered out by
        the opt-out, review-exclusion, or attribution filters)."

        Design: Difficulty/boundary_precision_check/truncation_at_exact_cap_vs_one_cent_over
        """
        ctx = self._cap_boundary_period("ACO-TR2")
        res = api.get_expenditure_summary(ctx["period"]["id"], actuary_headers)
        summary = validate_success(res, 200)
        assert summary["truncated_away_cents"] == 1
        assert summary["included_beneficiary_count"] == 2
        assert summary["excluded_claim_count"] == 0


class TestExpenditureInputSet:
    def test_expenditure_input_set_excludes_received_and_voided(self, api, actuary_headers,
                                                                claims_headers):
        """PRD §3.6: "The included input set is every `ADJUDICATED` claim of the
        period whose `review_excluded` flag is false, whose beneficiary holds an
        attribution record of the period in `FINAL` or `UNDER_APPEAL` status, and
        whose beneficiary was not opted out as of the claim's `service_date`".

        Design: Corner/calculations/expenditure_input_set_excludes_received_and_voided
        """
        period = create_period(tax_id="ACO-C4")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-C4", 1980)
        open_period(period["id"])
        c1 = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                          "PART_B", participant_id=participant["id"])
        ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 99000, "PART_A",
                     participant_id=participant["id"])  # stays RECEIVED
        c3 = ingest_claim(period["id"], beneficiary["id"], "2026-04-01", 50000,
                          "PART_A", participant_id=participant["id"])
        adjudicate(c1["id"])
        adjudicate(c3["id"])
        void_claim(c3["id"], reason="dup")
        run_alignment(period["id"])
        lock_period(period["id"])
        res = api.get_expenditure_summary(period["id"], actuary_headers)
        summary = validate_success(res, 200)
        assert summary["raw_adjudicated_total_cents"] == 20000
        assert summary["truncated_total_cents"] == 20000
        assert summary["included_beneficiary_count"] == 1
        assert summary["excluded_claim_count"] == 0


class TestHighCostFlagBoundary:
    def _threshold_claims(self, tax_id):
        """Beneficiary with claims 6000000, 3999999, and 1 cent (PART_A)."""
        period = create_period(tax_id=tax_id)
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-HB-1", 1980)
        open_period(period["id"])
        c1 = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 6000000,
                          "PART_A", participant_id=participant["id"])
        c2 = ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 3999999,
                          "PART_A", participant_id=participant["id"])
        c3 = ingest_claim(period["id"], beneficiary["id"], "2026-04-01", 1,
                          "PART_A", participant_id=participant["id"])
        return period, beneficiary, c1, c2, c3

    def test_ytd_one_cent_below_threshold_does_not_flag(self, api, admin_headers):
        """PRD §3.2: "The boundary is inclusive: a total of exactly 10000000
        cents flags the beneficiary; one cent below does not."

        Design: Difficulty/boundary_precision_check/high_cost_flag_at_exact_threshold
        """
        _period, beneficiary, c1, c2, _c3 = self._threshold_claims("ACO-HB")
        adjudicate(c1["id"])
        adjudicate(c2["id"])  # YTD 9999999
        res = api.list_high_cost_reviews(
            admin_headers, params={"beneficiary_id": beneficiary["id"]},
        )
        _reviews, meta = validate_paginated(res)
        assert meta["total_count"] == 0

    def test_ytd_at_exact_threshold_flags_review(self, api, admin_headers):
        """PRD §3.2: "When an adjudication pushes that total (including the
        just-adjudicated claim) to at least 10000000 cents — one hundred thousand
        dollars — and no `FLAGGED` high-cost review already exists for the
        beneficiary in that period, the system creates a `HighCostReview` in
        `FLAGGED` status, recording the current year-to-date figure as
        `flagged_expenditure_cents`."

        Design: Difficulty/boundary_precision_check/high_cost_flag_at_exact_threshold
        """
        _period, beneficiary, c1, c2, c3 = self._threshold_claims("ACO-HB2")
        adjudicate(c1["id"])
        adjudicate(c2["id"])
        adjudicate(c3["id"])  # YTD exactly 10000000
        res = api.list_high_cost_reviews(
            admin_headers, params={"beneficiary_id": beneficiary["id"]},
        )
        reviews, meta = validate_paginated(res)
        assert meta["total_count"] == 1
        assert reviews[0]["status"] == "FLAGGED"
        assert reviews[0]["flagged_expenditure_cents"] == 10000000


class TestFlagThenAutoDismiss:
    def _flagged_review(self, tax_id):
        """Beneficiary with 6000000 + 4000000 PART_A claims; adjudicating both
        crosses the threshold and flags a review."""
        period = create_period(tax_id=tax_id)
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-FD-1", 1980)
        open_period(period["id"])
        c1 = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 6000000,
                          "PART_A", participant_id=participant["id"])
        c2 = ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 4000000,
                          "PART_A", participant_id=participant["id"])
        return period, beneficiary, c1, c2

    def test_adjudication_crossing_flags_review(self, api, admin_headers):
        """PRD §3.2: "The platform maintains a running year-to-date adjudicated
        total per beneficiary per period — the sum of `allowed_amount_cents`
        over that beneficiary's `ADJUDICATED` claims in the period. When an
        adjudication pushes that total (including the just-adjudicated claim) to
        at least 10000000 cents — one hundred thousand dollars — and no
        `FLAGGED` high-cost review already exists for the beneficiary in that
        period, the system creates a `HighCostReview` in `FLAGGED` status".

        Design: Difficulty/compensating_invariant/flag_then_auto_dismiss_conserves_flagged_review_count
        """
        _period, beneficiary, c1, c2 = self._flagged_review("ACO-FD")
        adjudicate(c1["id"])
        adjudicate(c2["id"])
        res = api.list_high_cost_reviews(
            admin_headers, params={"beneficiary_id": beneficiary["id"]},
        )
        reviews, meta = validate_paginated(res)
        assert meta["total_count"] == 1
        assert reviews[0]["status"] == "FLAGGED"

    def test_void_below_threshold_auto_dismisses_review(self, api, admin_headers):
        """PRD §3.2: "if a `FLAGGED` review exists and the total has fallen below
        the 10000000-cent threshold, that review is auto-dismissed — moved to
        `DISMISSED` with `dismissal_reason` set to `THRESHOLD_FALLEN`."

        Design: Difficulty/compensating_invariant/flag_then_auto_dismiss_conserves_flagged_review_count
        """
        period, beneficiary, c1, c2 = self._flagged_review("ACO-FD2")
        adjudicate(c1["id"])
        adjudicate(c2["id"])
        review = list_reviews(beneficiary_id=beneficiary["id"])[0]
        void_claim(c2["id"], reason="duplicate submission")
        after = validate_success(api.get_high_cost_review(review["id"], admin_headers), 200)
        assert after["status"] == "DISMISSED"
        assert after["dismissal_reason"] == "THRESHOLD_FALLEN"
        res = api.list_high_cost_reviews(
            admin_headers,
            params={"agreement_period_id": period["id"], "status": "FLAGGED"},
        )
        _reviews, meta = validate_paginated(res)
        assert meta["total_count"] == 0


class TestConfirmedExclusionCascade:
    def _flagged_proposed_settlement(self, tax_id):
        """Beneficiary BH (risk 1.00) with adjudicated 10000 PART_B + 6000000 +
        4000000 PART_A claims: the third adjudication crosses the threshold and
        auto-flags a review; period carried through a PROPOSED settlement with
        expenditure 10010000 against FINAL benchmark 1225200."""
        return build_period_scenario(
            tax_id=tax_id,
            beneficiaries=({"medicare_id": "MBI-HC-1", "birth_year": 1990},),
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 10000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 6000000, "claim_type": "PART_A"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-04-01",
                 "amount": 4000000, "claim_type": "PART_A"},
            ),
            settlement=True,
        )

    def test_confirmed_exclusion_marks_claims_review_excluded(self, api, admin_headers):
        """PRD §3.2: "`CONFIRMED_EXCLUSION` declares the beneficiary's costs
        excludable: every `ADJUDICATED` claim line of that beneficiary in the
        period is marked `review_excluded` true".

        Design: Difficulty/transitive_cascade/cascade_high_cost_determine_to_claims_to_stale
        """
        ctx = self._flagged_proposed_settlement("ACO-HC")
        review = list_reviews(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
        assert review["flagged_expenditure_cents"] == 10010000
        assert ctx["settlement"]["status"] == "PROPOSED"
        assert ctx["settlement"]["expenditure_total_cents"] == 10010000

        determined = determine_review(review["id"], "CONFIRMED_EXCLUSION",
                                      rationale="outlier verified")
        assert determined["status"] == "CONFIRMED_EXCLUSION"
        for claim in ctx["claims"]:
            after = validate_success(api.get_claim(claim["id"], admin_headers), 200)
            assert after["review_excluded"] is True

    def test_confirmed_exclusion_stales_settlement_and_empties_expenditure(
            self, api, actuary_headers):
        """PRD §3.2: "every `ADJUDICATED` claim line of that beneficiary in the
        period is marked `review_excluded` true, which removes those claims from
        the expenditure input set, and any `PROPOSED` settlement of the period
        cascades to `STALE`".

        Design: Difficulty/transitive_cascade/cascade_high_cost_determine_to_claims_to_stale
        """
        ctx = self._flagged_proposed_settlement("ACO-HC2")
        review = list_reviews(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
        determine_review(review["id"], "CONFIRMED_EXCLUSION",
                         rationale="outlier verified")
        settlement_after = validate_success(
            api.get_settlement(ctx["settlement"]["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "STALE"
        summary = validate_success(
            api.get_expenditure_summary(ctx["period"]["id"], actuary_headers), 200,
        )
        assert summary["truncated_total_cents"] == 0
        assert summary["excluded_claim_count"] == 3


class TestDetermineGate:
    def test_determine_determined_review_rejected(self, api, review_officer_headers):
        """PRD §3.2: "Determination is only possible while the review is
        `FLAGGED`; otherwise the call is rejected with `ERR_REVIEW_NOT_FLAGGED`
        (HTTP 409)."

        Design: Corner/errors/determine_determined_review_rejected
        """
        period = create_period(tax_id="ACO-Z4")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-Z4", 1980)
        open_period(period["id"])
        c1 = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 6000000,
                          "PART_A", participant_id=participant["id"])
        c2 = ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 4000000,
                          "PART_A", participant_id=participant["id"])
        adjudicate(c1["id"])
        adjudicate(c2["id"])
        review = list_reviews(beneficiary_id=beneficiary["id"])[0]
        determine_review(review["id"], "DISMISSED", rationale="reviewed ok")
        res = api.determine_high_cost_review(
            review["id"], {"outcome": "CONFIRMED_EXCLUSION"}, review_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_NOT_FLAGGED, expected_status=409)
