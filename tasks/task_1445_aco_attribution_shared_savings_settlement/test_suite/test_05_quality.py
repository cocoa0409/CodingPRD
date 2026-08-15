"""Quality reporting: scoring math, review cycle, segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_period,
    create_quality_score_payload,
    make_quality_auditor_headers,
    make_quality_reporter_headers,
    open_period,
    propose_settlement,
    report_score,
    resubmit_score_payload,
    review_score,
    review_score_payload,
    setup_lite_proposed_settlement,
    validate_error,
    validate_success,
    build_period_scenario,
    QUALITY_REPORTER_1,
    QUALITY_AUDITOR_1,
)


class TestScoreLifecycle:
    def test_score_review_after_validated_rejected(self, api, quality_auditor_headers):
        """PRD §3.5: "Reviewing a score in any other status is rejected with
        `ERR_SCORE_INVALID_STATE`".

        Design: Corner/state_machines/score_review_after_validated_rejected
        """
        period = create_period(tax_id="ACO-S3")
        open_period(period["id"])
        score = report_score(period["id"], "M1", 3, 4, 10)
        review_score(score["id"], "VALIDATED")
        res = api.review_quality_score(
            score["id"], review_score_payload("REJECTED"), quality_auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_SCORE_INVALID_STATE, expected_status=409)

    def test_duplicate_measure_score_rejected(self, api):
        """PRD §3.5: "a `measure_code` (unique within the period across all
        scores, so a second report for the same measure draws
        `ERR_DUPLICATE_MEASURE_SCORE`)".

        Design: Corner/validations/duplicate_measure_score_rejected
        """
        period = create_period(tax_id="ACO-V8")
        open_period(period["id"])
        report_score(period["id"], "M1", 3, 4, 10, reporter="qr-1")
        res = api.create_quality_score(
            create_quality_score_payload(period["id"], measure_code="M1", numerator=1,
                                         denominator=2, max_points=10),
            make_quality_reporter_headers("qr-2"),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_MEASURE_SCORE, expected_status=409)


class TestRejectResubmitCycle:
    def _setup_rejected_score(self, api):
        period = create_period(tax_id="ACO-QC")
        open_period(period["id"])
        score = report_score(period["id"], "M1", 3, 4, 10, reporter="qr-1")
        rejected = review_score(score["id"], "REJECTED", auditor="qa-1")
        return period, score, rejected

    def test_rejected_score_resubmit_returns_to_reported(self, api):
        """PRD §3.5: "A `QualityReporter` may resubmit a `REJECTED` score with a
        corrected `numerator` and `denominator`, which recomputes
        `performance_rate` and `earned_points`, refreshes `reported_by_user_id`
        to the resubmitting user, and returns the score to `REPORTED`."

        Design: Difficulty/non_linear_state_machine/quality_score_reject_resubmit_cycle
        """
        _period, score, rejected = self._setup_rejected_score(api)
        assert rejected["status"] == "REJECTED"
        res = api.resubmit_quality_score(
            score["id"], resubmit_score_payload(4, 5),
            make_quality_reporter_headers("qr-2"),
        )
        resubmitted = validate_success(res, 200)
        assert resubmitted["status"] == "REPORTED"
        assert resubmitted["performance_rate"] == pytest.approx(0.8)
        assert resubmitted["earned_points"] == pytest.approx(8.0)

    def test_resubmit_refreshes_reporter_and_allows_review(self, api):
        """PRD §3.5: "refreshes `reported_by_user_id` to the resubmitting user".
        PRD §3.5: "Validation is the terminal good state".

        Design: Difficulty/non_linear_state_machine/quality_score_reject_resubmit_cycle
        """
        _period, score, _rejected = self._setup_rejected_score(api)
        res = api.resubmit_quality_score(
            score["id"], resubmit_score_payload(4, 5),
            make_quality_reporter_headers("qr-2"),
        )
        resubmitted = validate_success(res, 200)
        assert resubmitted["reported_by_user_id"] == "qr-2"
        validated = validate_success(
            api.review_quality_score(
                score["id"], review_score_payload("VALIDATED"),
                make_quality_auditor_headers("qa-1"),
            ),
            200,
        )
        assert validated["status"] == "VALIDATED"


class TestSegregationOfDutiesOnReview:
    def test_quality_reviewer_must_not_be_reporter(self, api):
        """PRD §2.9: "A quality review is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the reviewing `X-User-ID`
        equals the score's `reported_by_user_id`."

        Design: Corner/rbac/quality_reviewer_must_not_be_reporter
        """
        period = create_period(tax_id="ACO-R4")
        open_period(period["id"])
        score = report_score(period["id"], "M1", 3, 4, 10, reporter="qr-1")
        res = api.review_quality_score(
            score["id"], review_score_payload("VALIDATED"),
            make_quality_auditor_headers("qr-1"),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        ok = validate_success(
            api.review_quality_score(
                score["id"], review_score_payload("VALIDATED"),
                make_quality_auditor_headers("qa-1"),
            ),
            200,
        )
        assert ok["status"] == "VALIDATED"


def _partial_tier_scenario(tax_id, numerator, denominator):
    """One-beneficiary period: FINAL benchmark 1715280 (risk 1.40), expenditure
    1670000 (20000 PART_B + 1650000 PART_A), single validated score."""
    return build_period_scenario(
        tax_id=tax_id,
        claims=(
            {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
             "amount": 20000, "claim_type": "PART_B"},
            {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
             "amount": 1650000, "claim_type": "PART_A"},
        ),
        quality_scores=(("M1", numerator, denominator, 10),),
        settlement=True,
    )


class TestQualityTiersInSettlement:
    def test_quality_partial_tier_multiplier_snapshot(self, api):
        """PRD §3.5: "an aggregate of at least 0.5000 but below 0.7000 earns a
        partial multiplier equal to the aggregate divided by 0.7000, rounded
        half-up to four decimals".

        Design: Corner/calculations/quality_partial_tier_multiplier_snapshot
        """
        ctx = _partial_tier_scenario("ACO-C2", 3, 5)
        settlement = ctx["settlement"]
        assert settlement["quality_score_snapshot"] == pytest.approx(0.6)
        assert settlement["quality_multiplier_snapshot"] == pytest.approx(0.8571)
        assert settlement["gross_savings_cents"] == 45280
        assert settlement["shared_savings_pre_sequestration_cents"] == 15524
        assert settlement["sequestration_levy_cents"] == 310
        assert settlement["net_shared_savings_cents"] == 15214

    def test_quality_below_gate_zeroes_savings(self, api):
        """PRD §3.5: "an aggregate below 0.5000 earns a multiplier of 0.0000".

        Design: Corner/calculations/quality_below_gate_zeroes_savings
        """
        ctx = _partial_tier_scenario("ACO-C3", 2, 5)
        settlement = ctx["settlement"]
        assert settlement["quality_multiplier_snapshot"] == pytest.approx(0.0)
        assert settlement["gross_savings_cents"] == 45280
        assert settlement["shared_savings_pre_sequestration_cents"] == 0
        assert settlement["distributable_pool_cents"] == 0


class TestQualityTierBoundary:
    def _full_tier_boundary_scenario(self, tax_id):
        """Aggregate exactly 0.7000: M1 3/4 (earned 7.50) + M2 13/20 (earned
        6.50) over 20 max points; canonical two-beneficiary expenditure
        2881670 against FINAL benchmark 2940480 (gross 58810 == MSR)."""
        return build_period_scenario(
            tax_id=tax_id,
            beneficiaries=(
                {"medicare_id": "MBI-QG-R", "birth_year": 1960,
                 "dual_eligible": True, "disabled": True},
                {"medicare_id": "MBI-QG-P", "birth_year": 1990},
            ),
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 1500000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-03-02",
                 "amount": 1341670, "claim_type": "PART_A"},
            ),
            quality_scores=(("M1", 3, 4, 10), ("M2", 13, 20, 10)),
            settlement=True,
        )

    def test_quality_aggregate_exactly_at_full_tier_boundary(self, api):
        """PRD §3.5: "an aggregate of at least 0.7000 earns the full multiplier
        1.0000".

        Design: Difficulty/combinatorial_formula/quality_gate_tiered_multiplier_branches
        """
        ctx = self._full_tier_boundary_scenario("ACO-QG")
        settlement = ctx["settlement"]
        assert settlement["quality_score_snapshot"] == pytest.approx(0.7)
        assert settlement["quality_multiplier_snapshot"] == pytest.approx(1.0)

    def test_full_tier_boundary_drives_pre_sequestration_amount(self, api):
        """PRD §3.6: "An eligible settlement's
        `shared_savings_pre_sequestration_cents` is the smaller of two
        rounded-half-up quantities: gross multiplied by the track's base rate
        multiplied by the quality multiplier, and ten percent of B (the savings
        cap)" and "savings eligibility requires gross to be at least the MSR
        threshold — meeting the threshold exactly qualifies".

        Design: Difficulty/combinatorial_formula/quality_gate_tiered_multiplier_branches
        """
        ctx = self._full_tier_boundary_scenario("ACO-QG2")
        settlement = ctx["settlement"]
        assert settlement["gross_savings_cents"] == 58810
        assert settlement["msr_threshold_cents"] == 58810
        # round(58810 x 0.40 x 1.0000) = 23524; savings cap round(0.10 x 2940480)
        assert settlement["shared_savings_pre_sequestration_cents"] == 23524
