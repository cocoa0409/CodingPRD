"""Credibility dual-variant scoring tests (Difficulty rule 1, instance 1)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_standard_cast,
    setup_investigating_case,
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    create_assessment,
    validate_success,
    get_success_data,
)


def _setup_investigating(cast):
    return setup_investigating_case(
        cast["channel"]["id"],
        cast["subject"]["id"],
        cast["inv_author"]["id"],
        reporter_employee_id=cast["reporter"]["id"],
        category="HARASSMENT",
        severity="MEDIUM",
    )


class TestCredibilityVariants:
    def test_corroboration_and_recency_variants_diverge(self):
        """PRD §3.4: "Every assessment is scored twice at creation, under two
        sanctioned variants over the same inputs, and the results are stored side
        by side as `score_corroboration` and `score_recency`."
        PRD §3.4: "The `CORROBORATION_WEIGHTED` variant starts from a base of
        0.50. It adds 0.10 for each independent corroborating source, counting at
        most four sources no matter how large the tally runs, and subtracts 0.15
        for each material contradiction, counting at most three."
        PRD §3.4: "The `RECENCY_WEIGHTED` variant starts from the same base of
        0.50 but prices staleness in. Corroboration contributes only 0.06 per
        source (still counting at most four), contradictions subtract 0.10 each
        (still at most three), and an additional recency decay subtracts 0.005
        for each day of account age, counting at most sixty days."

        Design: Difficulty/dual_variant_calc/credibility_variants_diverge_on_same_inputs
        """
        cast = setup_standard_cast()
        case = _setup_investigating(cast)
        resp = api_client.create_credibility_assessment(
            case["id"],
            {
                "subject_employee_id": cast["subject"]["id"],
                "corroboration_count": 3,
                "contradiction_count": 0,
                "account_age_days": 10,
            },
            make_investigator_headers(cast["inv_author"]["id"]),
        )
        ca = validate_success(resp, 201)
        # CORROBORATION_WEIGHTED: 0.50 + 0.10*3 - 0.15*0 = 0.80
        assert ca["score_corroboration"] == pytest.approx(0.80, abs=1e-6), (
            f"score_corroboration expected 0.80, got {ca['score_corroboration']}"
        )
        # RECENCY_WEIGHTED: 0.50 + 0.06*3 - 0.10*0 - 0.005*10 = 0.63
        assert ca["score_recency"] == pytest.approx(0.63, abs=1e-6), (
            f"score_recency expected 0.63, got {ca['score_recency']}"
        )
        assert ca["score_corroboration"] != ca["score_recency"]
        assert ca["active_variant"] == "CORROBORATION_WEIGHTED"

    def test_active_variant_defaults_to_corroboration_weighted(self):
        """PRD §3.4: "Which of the two scores downstream gates consult is decided
        by the assessment's `active_variant`, which starts at
        `CORROBORATION_WEIGHTED` for every case in its first investigation pass."

        Design: Difficulty/dual_variant_calc/credibility_variants_diverge_on_same_inputs
        """
        cast = setup_standard_cast()
        case = _setup_investigating(cast)
        resp = api_client.create_credibility_assessment(
            case["id"],
            {
                "subject_employee_id": cast["subject"]["id"],
                "corroboration_count": 1,
                "contradiction_count": 1,
                "account_age_days": 20,
            },
            make_investigator_headers(cast["inv_author"]["id"]),
        )
        ca = validate_success(resp, 201)
        assert ca["active_variant"] == "CORROBORATION_WEIGHTED", (
            f"Default active_variant expected CORROBORATION_WEIGHTED, got {ca['active_variant']}"
        )
        # Both variants computed and stored side by side
        assert "score_corroboration" in ca
        assert "score_recency" in ca
        # Variant math: 0.50 + 0.10*1 - 0.15*1 = 0.45 (corro)
        assert ca["score_corroboration"] == pytest.approx(0.45, abs=1e-6)
        # Variant math: 0.50 + 0.06*1 - 0.10*1 - 0.005*20 = 0.36 (recency)
        assert ca["score_recency"] == pytest.approx(0.36, abs=1e-6)
