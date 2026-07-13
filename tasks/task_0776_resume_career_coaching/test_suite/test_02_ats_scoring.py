"""ATS keyword scoring: strict vs semantic variants, the pinned per-section
rounding order, and the deliverable's refreshed current scores."""
from test_helpers import (
    validate_success,
    setup_drafted_deliverable,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

ATS_PLAN = {
    "tier": "PRO",
    "base_price_cents": 30000,
    "included_deliverables": ["RESUME"],
    "included_revision_rounds": 1,
    "included_coaching_sessions": 0,
    "includes_ats": True,
    "guarantee_type": "NONE",
}


class TestStrictVsSemantic:
    SECTIONS = [
        {"name": "SUMMARY", "weight": 1, "keywords_total": 4, "matched_strict": 3, "matched_semantic": 4},
        {"name": "EXPERIENCE", "weight": 3, "keywords_total": 10, "matched_strict": 6, "matched_semantic": 8},
    ]

    def _scan(self, api):
        ctx = setup_drafted_deliverable(plan_overrides=ATS_PLAN)
        resp = api.create_ats_scan(ctx["deliverable_id"], {"sections": self.SECTIONS}, ctx["coach_headers"])
        return validate_success(resp, 201)

    def test_strict_score_counts_exact_matches(self, api):
        """PRD §3.4: "the strict_score is the weighted sum of the per-section strict
        percents divided by the total weight and rounded half up to a whole number".
        SUMMARY 75% (w1) and EXPERIENCE 60% (w3) weight-average to 64.

        Design: Difficulty/dual_variant_calc/ats_strict_vs_semantic_score
        """
        data = self._scan(api)
        assert data["strict_score"] == 64, f"expected strict 64, got {data['strict_score']}"

    def test_semantic_score_counts_synonyms_and_is_at_least_strict(self, api):
        """PRD §3.4: "Because matched_semantic is never less than matched_strict, the
        semantic score is never less than the strict score for the same résumé."
        SUMMARY 100% (w1) and EXPERIENCE 80% (w3) weight-average to 85.

        Design: Difficulty/dual_variant_calc/ats_strict_vs_semantic_score
        """
        data = self._scan(api)
        assert data["semantic_score"] == 85, f"expected semantic 85, got {data['semantic_score']}"
        assert data["semantic_score"] >= data["strict_score"]
        assert data["semantic_score"] != data["strict_score"]


class TestRoundingOrder:
    SECTIONS = [
        {"name": "S1", "weight": 1, "keywords_total": 8, "matched_strict": 1, "matched_semantic": 1},
        {"name": "S2", "weight": 1, "keywords_total": 8, "matched_strict": 3, "matched_semantic": 3},
    ]

    def _scan(self, api):
        ctx = setup_drafted_deliverable(plan_overrides=ATS_PLAN)
        resp = api.create_ats_scan(ctx["deliverable_id"], {"sections": self.SECTIONS}, ctx["coach_headers"])
        return validate_success(resp, 201)

    def test_per_section_rounding_before_aggregation(self, api):
        """PRD §3.4: "These per-section percents are rounded first, before any
        aggregation." Rounding S1 to 13 and S2 to 38 first yields a weighted average of
        25.5 that rounds to 26 (an aggregate-then-round path would give 25).

        Design: Difficulty/combinatorial_formula/ats_rounding_order_per_section_first
        """
        data = self._scan(api)
        assert data["strict_score"] == 26, f"expected 26, got {data['strict_score']}"

    def test_coverage_by_section_reports_rounded_percents(self, api):
        """PRD §3.4: "The scan also records `coverage_by_section`, a map from each
        section's `name` to its whole-number strict coverage percent." 1/8 rounds half up
        to 13 and 3/8 rounds half up to 38.

        Design: Difficulty/combinatorial_formula/ats_rounding_order_per_section_first
        """
        data = self._scan(api)
        assert data["coverage_by_section"]["S1"] == 13
        assert data["coverage_by_section"]["S2"] == 38


def test_deliverable_current_strict_score_reflects_latest_scan(api):
    """PRD §3.4: "After a scan, the deliverable's current_strict_ats_score and
    current_semantic_ats_score are refreshed to the strict and semantic scores of the
    most recent scan by creation time". A single section matching 2 of 4 keywords scores 50.

    Design: Corner/entities/deliverable_computed_ats_score_reflects_latest_scan
    """
    ctx = setup_drafted_deliverable(plan_overrides=ATS_PLAN)
    sections = [{"name": "S1", "weight": 1, "keywords_total": 4, "matched_strict": 2, "matched_semantic": 2}]
    validate_success(api.create_ats_scan(ctx["deliverable_id"], {"sections": sections}, ctx["coach_headers"]), 201)
    deliverable = validate_success(api.get_deliverable(ctx["deliverable_id"], ADMIN))
    assert deliverable["current_strict_ats_score"] == 50
