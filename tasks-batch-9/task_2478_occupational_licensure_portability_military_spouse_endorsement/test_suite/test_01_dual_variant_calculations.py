"""Two calculations that carry two variants at once: the substantial-equivalency
score under STRICT_SCOPE versus UNIVERSAL_RECOGNITION, and the disciplinary risk
index anchored on `reported_at` versus `action_effective_at`."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ENTRY_EXAM_FEE_REVERSAL,
    MEMO_EXAM_FEE_REVERSAL,
    OVERALL_COMPLETE,
    PATHWAY_UNIVERSAL_RECOGNITION,
    SCOPE_DEFICIENT,
    SEVERITY_ADVISORY,
    SEVERITY_PROBATION,
    VARIANT_STRICT_SCOPE,
    VARIANT_UNIVERSAL_RECOGNITION,
    assert_applicant_fields,
    assert_evaluation_fields,
    assert_memo,
    assert_risk_index_in_range,
    assert_score_in_range,
    ledger_signature,
    validate_paginated,
)

GRANTED_SCOPE = ["ASSESS", "TREAT", "SUPERVISE"]


@pytest.fixture
def two_variant_arms(setup):
    """Two applications carrying byte-identical credential data, one on the
    ENDORSEMENT pathway and one on UNIVERSAL_RECOGNITION, both walked to the point
    where only finalisation remains."""
    profession = setup.profession()
    prof_code = profession["profession_code"]

    arms = {}
    for key, name, pathway, license_number in (
        ("a", "Dana Reyes", "ENDORSEMENT", "OK-70001"),
        ("b", "Kai Moreno", PATHWAY_UNIVERSAL_RECOGNITION, "OK-70002"),
    ):
        applicant = setup.applicant(full_name=name, state_code="TX", residency_months=24)
        credential = setup.credential(
            applicant["id"],
            issuing_state="OK",
            license_number=license_number,
            scope_elements=GRANTED_SCOPE,
            practice_hours=1200,
            verified_good_standing=True,
        )
        application = setup.application(
            applicant["id"], profession["id"], credential["id"], pathway=pathway
        )
        setup.submit(application["id"], applicant["id"])
        evaluation = setup.evaluation(application["id"], credential["id"])
        setup.scope_review(evaluation["id"], SCOPE_DEFICIENT)
        arms[key] = {
            "ap_id": applicant["id"],
            "cred_id": credential["id"],
            "app_id": application["id"],
            "eval_id": evaluation["id"],
        }

    evaluator = setup.evaluator(full_name="Eli Vance", profession_code=prof_code)
    setup.review_assignment(
        evaluator["id"], arms["a"]["app_id"], "2026-08-02T00:00:00Z", "2026-08-09T00:00:00Z"
    )
    setup.review_assignment(
        evaluator["id"], arms["b"]["app_id"], "2026-08-11T00:00:00Z", "2026-08-14T00:00:00Z"
    )
    for key in ("a", "b"):
        setup.discipline_finding(
            arms[key]["eval_id"], evaluator["id"], databases_checked=["NPDB", "NURSYS"]
        )

    return {"profession": profession, "evaluator": evaluator, **arms}


class TestEquivalencyVariantDivergence:
    def test_variant_is_pinned_from_the_pathway_at_evaluation_creation(self, two_variant_arms, setup):
        """PRD §3.5: "Its `variant` is pinned at creation from the application's
        pathway and never changes afterwards: `UNIVERSAL_RECOGNITION` when the
        pathway is `UNIVERSAL_RECOGNITION`, and `STRICT_SCOPE` for both
        `ENDORSEMENT` and `MILITARY_SPOUSE_EXPEDITED`."

        Design: Difficulty/dual_variant_calc/equivalency_variant_divergence_strict_vs_universal
        """
        arm_a = setup.read_evaluation(two_variant_arms["a"]["eval_id"])
        arm_b = setup.read_evaluation(two_variant_arms["b"]["eval_id"])

        assert_evaluation_fields(arm_a, variant=VARIANT_STRICT_SCOPE)
        assert_evaluation_fields(arm_b, variant=VARIANT_UNIVERSAL_RECOGNITION)
        assert_evaluation_fields(
            arm_a,
            matched_scope_elements=GRANTED_SCOPE,
            missing_scope_elements=["PRESCRIBE"],
        )
        assert_evaluation_fields(
            arm_b,
            matched_scope_elements=GRANTED_SCOPE,
            missing_scope_elements=["PRESCRIBE"],
        )

    def test_identical_credential_data_scores_twenty_points_higher_under_universal_recognition(
        self, api, two_variant_arms, setup
    ):
        """PRD §3.5: "Count how many members of `missing_scope_elements` also
        appear in the profession's `critical_scope_elements`; under the
        `STRICT_SCOPE` variant the penalty is 10.0 points for each such critical
        miss, and under the `UNIVERSAL_RECOGNITION` variant the penalty is zero
        and critical misses are ignored entirely."

        Design: Difficulty/dual_variant_calc/equivalency_variant_divergence_strict_vs_universal
        """
        setup.finalize(two_variant_arms["a"]["eval_id"])
        setup.finalize(two_variant_arms["b"]["eval_id"])

        arm_a = setup.read_evaluation(two_variant_arms["a"]["eval_id"])
        arm_b = setup.read_evaluation(two_variant_arms["b"]["eval_id"])

        assert_score_in_range(arm_a["equivalency_score"])
        assert_score_in_range(arm_b["equivalency_score"])
        assert arm_a["equivalency_score"] == 65.00, (
            "strict scope: 0.75*0.60 + 0.60*0.25 + 1.0*0.15 = 0.75, times 100, "
            "less the 10.0 critical-miss penalty"
        )
        assert arm_b["equivalency_score"] == 85.00, (
            "universal recognition: residency lifts the hours ratio to 1.0 and the "
            "critical miss draws no penalty"
        )
        assert round(arm_b["equivalency_score"] - arm_a["equivalency_score"], 2) == 20.00
        assert_evaluation_fields(arm_a, overall_status=OVERALL_COMPLETE)
        assert_evaluation_fields(arm_b, overall_status=OVERALL_COMPLETE)

    def test_only_the_universal_recognition_arm_clears_the_waiver_threshold_and_reverses_the_seat_fee(
        self, two_variant_arms, setup
    ):
        """PRD §3.5: "The system appends an `EXAM_FEE_REVERSAL` entry with the memo
        `exam fee reversal` whose `amount_cents` is the negative of the applicant's
        own share of the examination component — that is, the profession's
        `exam_fee_cents` less the amount already waived, where the amount already
        waived is `exam_fee_cents` multiplied by the application's frozen
        `statutory_waiver_pct` and rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/equivalency_variant_divergence_strict_vs_universal
        """
        setup.finalize(two_variant_arms["a"]["eval_id"])
        setup.finalize(two_variant_arms["b"]["eval_id"])

        arm_a = setup.read_evaluation(two_variant_arms["a"]["eval_id"])
        arm_b = setup.read_evaluation(two_variant_arms["b"]["eval_id"])
        assert_evaluation_fields(arm_a, exam_waiver_granted=False)
        assert_evaluation_fields(arm_b, exam_waiver_granted=True)

        ledger_a = setup.read_ledger(two_variant_arms["a"]["app_id"])
        ledger_b = setup.read_ledger(two_variant_arms["b"]["app_id"])
        assert ENTRY_EXAM_FEE_REVERSAL not in [row["entry_type"] for row in ledger_a], (
            "no waiver was granted on the strict-scope arm, so no seat fee comes back"
        )
        reversals = [row for row in ledger_b if row["entry_type"] == ENTRY_EXAM_FEE_REVERSAL]
        assert len(reversals) == 1, f"expected one reversal, got {ledger_signature(ledger_b)}"
        assert reversals[0]["amount_cents"] == -8000
        assert_memo(reversals[0], MEMO_EXAM_FEE_REVERSAL)

        assert setup.read_application(two_variant_arms["a"]["app_id"])["fee_balance_cents"] == 48000
        assert setup.read_application(two_variant_arms["b"]["app_id"])["fee_balance_cents"] == 40000


class TestRiskIndexVariantDivergence:
    @pytest.fixture
    def aged_history(self, setup):
        """One unresolved PROBATION record whose surfacing lags its effective date
        by two years, read at a clock two years further on."""
        setup.set_clock("2027-03-01T00:00:00Z")
        applicant = setup.applicant(full_name="Rowan Pike", state_code="TX", residency_months=36)
        first = setup.disciplinary_record(
            applicant["id"],
            source_state="NM",
            source_database="NPDB",
            severity=SEVERITY_PROBATION,
            action_effective_at="2024-02-01T00:00:00Z",
            reported_at="2026-02-01T00:00:00Z",
        )
        return {"ap_id": applicant["id"], "dr1": first["id"]}

    def test_the_two_index_variants_diverge_because_each_ages_from_its_own_timestamp(
        self, aged_history, setup
    ):
        """PRD §3.3: "Order the gathered rows by that variant's timestamp key
        ascending — `reported_at` for the reported variant, `action_effective_at`
        for the effective variant — breaking ties by `created_at` ascending and
        never by identifier."

        Design: Difficulty/dual_variant_calc/risk_index_reported_vs_effective_variant_divergence
        """
        setup.disciplinary_record(
            aged_history["ap_id"],
            source_state="AZ",
            source_database="NURSYS",
            severity=SEVERITY_ADVISORY,
            action_effective_at="2025-06-01T00:00:00Z",
            reported_at="2026-06-01T00:00:00Z",
        )

        applicant = setup.read_applicant(aged_history["ap_id"])
        assert_risk_index_in_range(
            applicant["disciplinary_risk_index_effective"], "disciplinary_risk_index_effective"
        )
        assert_risk_index_in_range(
            applicant["disciplinary_risk_index_reported"], "disciplinary_risk_index_reported"
        )
        assert applicant["disciplinary_risk_index_effective"] == 10.00, (
            "effective ages the PROBATION row three whole years (15 * 0.40 = 6.00) and "
            "the ADVISORY row one (5 * 0.80 = 4.00)"
        )
        assert applicant["disciplinary_risk_index_reported"] == 17.00, (
            "reported ages the PROBATION row one whole year (15 * 0.80 = 12.00) and the "
            "ADVISORY row not at all (5 * 1.00 = 5.00)"
        )
        assert (
            round(
                applicant["disciplinary_risk_index_reported"]
                - applicant["disciplinary_risk_index_effective"],
                2,
            )
            == 7.00
        )

    def test_good_standing_reads_the_reported_variant_and_survives_below_the_ceiling(
        self, api, aged_history, setup
    ):
        """PRD §3.3: "Good standing is a conjunction of two independent conditions,
        and both must hold for `good_standing_flag` to be true: the applicant must
        have no unresolved disciplinary record whose `severity` is `SUSPENSION` or
        `REVOCATION`, and `disciplinary_risk_index_reported` must be strictly below
        the good-standing ceiling of 25.00."

        Design: Difficulty/dual_variant_calc/risk_index_reported_vs_effective_variant_divergence
        """
        second = setup.disciplinary_record(
            aged_history["ap_id"],
            source_state="AZ",
            source_database="NURSYS",
            severity=SEVERITY_ADVISORY,
            action_effective_at="2025-06-01T00:00:00Z",
            reported_at="2026-06-01T00:00:00Z",
        )

        applicant = setup.read_applicant(aged_history["ap_id"])
        assert_applicant_fields(applicant, good_standing_flag=True)
        assert applicant["disciplinary_risk_index_reported"] < 25.00

        records, _meta = validate_paginated(
            api.list_disciplinary_records(aged_history["ap_id"], ANALYST_HEADERS, {"limit": 100})
        )
        posted = {row["id"]: row for row in records}
        assert posted[second["id"]]["resolved"] is False
        assert posted[second["id"]]["resolved_at"] is None
