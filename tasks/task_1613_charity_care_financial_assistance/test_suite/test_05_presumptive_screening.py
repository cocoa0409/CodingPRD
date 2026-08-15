"""Presumptive eligibility screening: weighted scoring, thin-file
renormalization, outcome thresholds, and the 1:1 screening constraint."""
from test_helpers import (
    COUNSELOR,
    REVIEWER,
    ApiErrorId,
    assert_decimal_eq,
    assert_presumptive_screening,
    get_application,
    get_screening,
    setup_presumptive_application,
    validate_error,
)

FULL_FILE_SCORES = {
    "income_band_score": 95,
    "payment_history_score": 90,
    "utilization_score": 30,
    "public_benefit_score": 95,
    "housing_stability_score": 20,
}
THIN_FILE_SCORES = {
    "income_band_score": 95,
    "payment_history_score": 90,
    "public_benefit_score": 95,
}


class TestFullVsThinFile:
    def test_full_file_score_is_weighted_sum(self, api):
        """PRD §3.7: "The factor weights are 0.35 for income band, 0.25 for
        payment history, 0.15 for utilization, 0.15 for public benefit, and
        0.10 for housing stability — which for a complete file sum to exactly
        1.00. If fewer than three factor scores are present, the screening is
        rejected outright with `ERR_INSUFFICIENT_FACTORS` (HTTP 422). Otherwise
        the raw score is the sum over present factors of each factor's weight
        times its score. When all five factors are present (`thin_file` false),
        the `propensity_score` is that raw sum rounded half-up to 2 decimal
        places."

        Design: Difficulty/dual_variant_calc/presumptive_score_full_vs_thin_file_divergence
        """
        ctx = setup_presumptive_application(
            patient_name="Full File", mrn="MRN-FULL-1", ssn_last4="1111",
            screening_scores=FULL_FILE_SCORES,
        )
        screening = ctx["screening"]
        assert_presumptive_screening(screening)
        # 0.35*95 + 0.25*90 + 0.15*30 + 0.15*95 + 0.10*20 = 76.50
        assert_decimal_eq(screening["propensity_score"], 76.50, "propensity_score")
        assert screening["thin_file"] is False
        assert screening["present_factor_count"] == 5
        # 70.0 <= 76.50 < 90.0
        assert screening["outcome"] == "ELIGIBLE_PARTIAL"

    def test_thin_file_renormalization_raises_score(self, api):
        """PRD §3.7: "When only three or four factors are present (`thin_file`
        true), the raw sum is divided by the sum of the weights of the present
        factors only — a renormalization that yields a different score than
        treating absent factors as zero — and that quotient is rounded half-up
        to 2 decimal places."
        PRD §3.7: "The screening's `outcome` compares the `propensity_score`
        against the pinned policy's thresholds: a score at or above
        `presumptive_full_score_threshold` yields `ELIGIBLE_FULL`; a score at
        or above `presumptive_partial_score_threshold` (but below the full
        threshold) yields `ELIGIBLE_PARTIAL`; anything below yields
        `NOT_ELIGIBLE`."

        Design: Difficulty/dual_variant_calc/presumptive_score_full_vs_thin_file_divergence
        """
        ctx = setup_presumptive_application(
            patient_name="Thin File", mrn="MRN-THIN-1", ssn_last4="2222",
            screening_scores=THIN_FILE_SCORES,
        )
        screening = ctx["screening"]
        assert_presumptive_screening(screening)
        # (33.25 + 22.50 + 14.25) / (0.35 + 0.25 + 0.15) = 70.00 / 0.75 = 93.33
        assert_decimal_eq(screening["propensity_score"], 93.33, "propensity_score")
        assert screening["thin_file"] is True
        assert screening["present_factor_count"] == 3
        assert screening["outcome"] == "ELIGIBLE_FULL", (
            "93.33 >= full threshold 90.0 — the same present scores that scored "
            "76.50 as a full file flip outcome under renormalization"
        )


class TestScreeningConstraints:
    def test_second_screening_rejected(self, api):
        """PRD §3.7: "The screening is one-to-one with its application; a
        second attempt is rejected with `ERR_SCREENING_ALREADY_EXISTS`
        (HTTP 409)."

        Design: Corner/entities/screening_second_run_rejected
        """
        ctx = setup_presumptive_application(
            patient_name="Screen Sam", mrn="MRN-SCR-1", ssn_last4="0005",
            screening_scores={
                "income_band_score": 80,
                "payment_history_score": 80,
                "utilization_score": 80,
            },
        )
        app_id = ctx["application"]["id"]
        resp = api.run_presumptive_screening(
            app_id,
            {"income_band_score": 10, "payment_history_score": 10,
             "utilization_score": 10},
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCREENING_ALREADY_EXISTS)
        screenings = get_screening(app_id)
        assert len(screenings) == 1, "1:1 — the original screening is the only one"
        # (28 + 20 + 12) / 0.75 = 80.00
        assert_decimal_eq(screenings[0]["propensity_score"], 80.00, "propensity_score")

    def test_fewer_than_three_factors_rejected(self, api):
        """PRD §3.7: "If fewer than three factor scores are present, the
        screening is rejected outright with `ERR_INSUFFICIENT_FACTORS`
        (HTTP 422)."

        Design: Corner/validations/screening_with_fewer_than_three_factors_rejected
        """
        ctx = setup_presumptive_application(
            patient_name="Thin Two", mrn="MRN-THIN2-1", ssn_last4="0036",
        )
        resp = api.run_presumptive_screening(
            ctx["application"]["id"],
            {"income_band_score": 80, "payment_history_score": 80},
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FACTORS)


class TestOutcomeThresholds:
    def test_score_at_partial_threshold_eligible(self, api):
        """PRD §3.7: "The screening's `outcome` compares the `propensity_score`
        against the pinned policy's thresholds: a score at or above
        `presumptive_full_score_threshold` yields `ELIGIBLE_FULL`; a score at
        or above `presumptive_partial_score_threshold` (but below the full
        threshold) yields `ELIGIBLE_PARTIAL`; anything below yields
        `NOT_ELIGIBLE`."

        Design: Corner/calculations/presumptive_score_threshold_boundary_70
        """
        ctx = setup_presumptive_application(
            patient_name="Seventy Sue", mrn="MRN-S70-1", ssn_last4="0020",
            screening_scores={
                "income_band_score": 70,
                "payment_history_score": 70,
                "utilization_score": 70,
            },
        )
        screening = ctx["screening"]
        # thin file: (0.75 * 70) / 0.75 = 70.00 — exactly the partial threshold
        assert_decimal_eq(screening["propensity_score"], 70.00, "propensity_score")
        assert screening["outcome"] == "ELIGIBLE_PARTIAL", (
            "at-or-above is inclusive for the partial threshold"
        )

    def test_score_below_partial_threshold_not_eligible(self, api):
        """PRD §3.7: "The screening's `outcome` compares the `propensity_score`
        against the pinned policy's thresholds: a score at or above
        `presumptive_full_score_threshold` yields `ELIGIBLE_FULL`; a score at
        or above `presumptive_partial_score_threshold` (but below the full
        threshold) yields `ELIGIBLE_PARTIAL`; anything below yields
        `NOT_ELIGIBLE`."

        Design: Corner/calculations/presumptive_score_threshold_boundary_70
        """
        ctx = setup_presumptive_application(
            patient_name="Sixty Sid", mrn="MRN-S60-1", ssn_last4="0021",
            screening_scores={
                "income_band_score": 60,
                "payment_history_score": 60,
                "utilization_score": 60,
            },
        )
        screening = ctx["screening"]
        assert_decimal_eq(screening["propensity_score"], 60.00, "propensity_score")
        assert screening["outcome"] == "NOT_ELIGIBLE"

    def test_determination_below_threshold_rejected(self, api):
        """PRD §3.8: "Two basis-specific evidence gates apply: a
        `VERIFIED_APPLICATION` basis requires at least one `VERIFIED` income
        document (`PAY_STUB`, `TAX_RETURN`, or `BENEFIT_LETTER`) and at least
        one `VERIFIED` `IDENTITY` document on the application
        (`ERR_VERIFIED_DOCS_REQUIRED`, HTTP 422); a `PRESUMPTIVE_SCORE` basis
        requires a presumptive screening whose `outcome` is not `NOT_ELIGIBLE`
        (`ERR_PRESCREEN_BELOW_THRESHOLD`, HTTP 422)."

        Design: Corner/calculations/presumptive_determination_below_threshold_rejected
        """
        ctx = setup_presumptive_application(
            patient_name="Below Ben", mrn="MRN-BEL-1", ssn_last4="0022",
            accounts=((100000, 0),),
            screening_scores={
                "income_band_score": 60,
                "payment_history_score": 60,
                "utilization_score": 60,
            },
        )
        assert ctx["screening"]["outcome"] == "NOT_ELIGIBLE"
        app = get_application(ctx["application"]["id"])
        resp = api.create_determination(
            {
                "application_id": app["id"],
                "basis": "PRESUMPTIVE_SCORE",
                "covered_account_ids": [ctx["accounts"][0]["id"]],
                "expected_application_version": app["version"],
            },
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_PRESCREEN_BELOW_THRESHOLD)
