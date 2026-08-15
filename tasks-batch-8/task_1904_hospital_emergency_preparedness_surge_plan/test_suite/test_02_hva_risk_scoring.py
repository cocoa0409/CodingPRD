"""Hazard vulnerability analysis: dual-variant risk scoring, entry immutability
of client-supplied scores, finalize gate, and the plan-review trigger."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_hazard_assessment,
    create_hazard_assessment,
    hazard_entry,
    validate_error,
    validate_success,
)

EM = TEST_USERS["emergency_manager_headers"]

ENTRY = {"entry_key": "EQ", "hazard_name": "Earthquake", "category": "NATURAL",
         "probability": 2, "severity": 3, "preparedness": 1}


def _entry_score(hva, key):
    for e in hva["hazard_entries"]:
        if e["entry_key"] == key:
            return e["risk_score"]
    raise AssertionError(f"entry {key} not found in {hva['hazard_entries']}")


class TestDualVariantScoring:
    def test_two_factor_score_and_boundary_plan_review_trigger(self, api):
        """PRD §3.1: "Under the `TWO_FACTOR` model, an entry's `risk_score` is its
        `probability` multiplied by its `severity`, yielding a range of 0 to 9."
        PRD §3.1: "The cycle's `max_risk_score` is the largest `risk_score` across
        its entries, or zero when the cycle has no entries."
        PRD §3.1: "Finalization recomputes every score one last time, freezes the
        entries (further patches are then rejected as an illegal state with
        `ERR_INVALID_STATE`), advances the assessment's `version`, and sets
        `plan_review_triggered` to true when `max_risk_score` is at least 6 and to
        false otherwise."

        Design: Difficulty/dual_variant_calc/hva_two_factor_vs_three_factor_divergence
        """
        hva = create_hazard_assessment(
            fiscal_year="FY2026", scoring_model="TWO_FACTOR", hazard_entries=[dict(ENTRY)]
        )
        assert _entry_score(hva, "EQ") == 6, "2 * 3 = 6 at creation"

        finalized = validate_success(api.finalize_hazard_assessment(hva["id"], EM))
        assert_hazard_assessment(finalized)
        assert _entry_score(finalized, "EQ") == 6
        assert finalized["max_risk_score"] == 6
        assert finalized["plan_review_triggered"] is True, (
            "6 >= trigger score 6 — the boundary is inclusive"
        )
        assert finalized["status"] == "FINALIZED"

    def test_three_factor_mitigation_scores_higher_on_identical_inputs(self, api):
        """PRD §3.1: "Under the `THREE_FACTOR_MITIGATION` model, an entry's
        `risk_score` is its `probability` multiplied by the sum of its `severity`
        and the amount by which its `preparedness` falls short of three, yielding
        a range of 0 to 18; for identical inputs, the three-factor model scores
        strictly higher whenever `preparedness` is below 3."

        Design: Difficulty/dual_variant_calc/hva_two_factor_vs_three_factor_divergence
        """
        hva = create_hazard_assessment(
            fiscal_year="FY2026", scoring_model="THREE_FACTOR_MITIGATION",
            hazard_entries=[dict(ENTRY)],
        )
        assert _entry_score(hva, "EQ") == 10, "2 * (3 + (3 - 1)) = 10"

        finalized = validate_success(api.finalize_hazard_assessment(hva["id"], EM))
        assert _entry_score(finalized, "EQ") == 10
        assert finalized["max_risk_score"] == 10


class TestComputedEntryScore:
    def test_hazard_entry_risk_score_computed_input_ignored(self, api):
        """PRD §3.1: "Every entry's `risk_score` is computed by the server on every
        write — at creation, on each entry-replacing patch, and again at
        finalization — and any client-supplied `risk_score` is ignored."

        Design: Corner/entities/hazard_entry_risk_score_computed_input_ignored
        """
        hva = create_hazard_assessment(
            fiscal_year="FY2026",
            scoring_model="TWO_FACTOR",
            hazard_entries=[hazard_entry("HZ1", "Flood", "NATURAL", 2, 3, 0,
                                         risk_score=999)],
        )
        assert _entry_score(hva, "HZ1") == 6, "server computes 2*3=6, ignoring 999"
        assert hva["max_risk_score"] == 6


class TestFinalizeGate:
    def test_hva_finalize_empty_rejected(self, api):
        """PRD §3.1: "Finalizing the cycle — the `DRAFT` → `FINALIZED` transition —
        requires at least one hazard entry; finalizing an empty cycle is rejected
        with `ERR_HVA_NO_ENTRIES`."

        Design: Corner/validations/hva_finalize_empty_rejected
        """
        hva = create_hazard_assessment(fiscal_year="FY2026", scoring_model="TWO_FACTOR")
        resp = api.finalize_hazard_assessment(hva["id"], EM)
        validate_error(resp, ApiErrorId.ERR_HVA_NO_ENTRIES)
        reread = validate_success(api.get_hazard_assessment(hva["id"], EM))
        assert reread["status"] == "DRAFT", "rejected finalize leaves the cycle DRAFT"

    def test_hva_plan_review_trigger_below_threshold(self, api):
        """PRD §3.1: "Finalization recomputes every score one last time, freezes
        the entries (further patches are then rejected as an illegal state with
        `ERR_INVALID_STATE`), advances the assessment's `version`, and sets
        `plan_review_triggered` to true when `max_risk_score` is at least 6 and to
        false otherwise."

        Design: Corner/calculations/hva_plan_review_trigger_below_threshold
        """
        hva = create_hazard_assessment(
            fiscal_year="FY2026",
            scoring_model="TWO_FACTOR",
            hazard_entries=[hazard_entry("HZL", "Minor leak", "HAZMAT", 1, 3, 2)],
        )
        finalized = validate_success(api.finalize_hazard_assessment(hva["id"], EM))
        assert finalized["max_risk_score"] == 3, "1 * 3 = 3"
        assert finalized["plan_review_triggered"] is False, "3 < 6 → not triggered"
