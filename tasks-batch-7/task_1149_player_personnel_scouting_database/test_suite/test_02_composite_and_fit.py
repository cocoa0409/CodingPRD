"""Composite-grade rounding, tier boundary, fit score inputs (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    MED_HEADERS,
    add_board_entry,
    advance_prospect,
    api_client,
    area_headers,
    create_and_lock_report,
    create_director,
    create_draft_board,
    create_flag,
    create_prospect,
    create_report,
    create_roster_need,
    create_scout,
    director_headers,
    get_success_data,
    lock_report,
    submit_report,
)


class TestCompositeRoundPerContribution:
    """PRD §3.3 step 2 pins the rounding order: per-report contribution first,
    then the sum is rounded again."""

    def _setup_two_report_prospect(self):
        """scoutA weight 1.5 raw 8.23 (normalized 6.67); scoutB weight 1.0 raw 7.57
        (normalized 7.36). Weights 0.6 / 0.4 -> per-report rounded contributions
        4.00 and 2.94 -> composite 6.94 (NOT the forbidden 6.95)."""
        sa = create_scout(
            level="AREA",
            full_name="Scout A",
            weight=1.5,
            season_grade_mean=6.00,
            season_grade_stdev=2.00,
        )
        sb = create_scout(
            level="AREA",
            full_name="Scout B",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(sa, full_name="Round Prospect", position="OT", college="State U")
        ra = create_report(p1["id"], sa, raw_grade=8.23, scheme_fit=1.00)
        rb = create_report(p1["id"], sb, raw_grade=7.57, scheme_fit=1.00)
        submit_report(ra["id"], sa)
        submit_report(rb["id"], sb)
        na = lock_report(ra["id"], d1)["normalized_grade"]
        nb = lock_report(rb["id"], d1)["normalized_grade"]
        return sa, sb, d1, p1, na, nb

    def test_per_report_normalized_grades(self, api):
        """PRD §3.3 step 1: "subtracting the applicable mean from the report's
        `raw_grade` and dividing by the applicable standard deviation, then
        maps the z-score back onto the team scale by multiplying by 1.5 and
        adding 5.0, rounds the result half-up to 2 decimal places". Scout A:
        5.0 + 1.5*(8.23-6.00)/2.00 = 6.6725 -> 6.67. Scout B:
        5.0 + 1.5*(7.57-6.00)/1.00 = 7.355 -> 7.36.

        Design: Difficulty/combinatorial_formula/composite_round_per_contribution_then_sum
        """
        _, _, _, _, na, nb = self._setup_two_report_prospect()
        assert na == pytest.approx(6.67, abs=0.005)
        assert nb == pytest.approx(7.36, abs=0.005)

    def test_composite_uses_per_contribution_rounding(self, api):
        """PRD §3.3 step 2: "multiplies the fraction by the report's
        `normalized_grade`, and rounds the resulting contribution half-up to 2
        decimal places **per report first**. The per-report rounded
        contributions are then summed, and the sum is itself rounded half-up
        to 2 decimal places to produce the `composite_grade`. Summing
        unrounded products and rounding once is a different, forbidden order."
        Weights 1.5/2.5=0.6 and 1.0/2.5=0.4: 0.6*6.67 -> 4.002 -> 4.00;
        0.4*7.36 -> 2.944 -> 2.94; sum 6.94. The forbidden order yields
        round2(6.946) = 6.95.

        Design: Difficulty/combinatorial_formula/composite_round_per_contribution_then_sum
        """
        _, _, d1, p1, _, _ = self._setup_two_report_prospect()
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["composite_grade"] == pytest.approx(6.94, abs=0.005), (
            f"per-contribution rounding must give 6.94, not the forbidden "
            f"sum-then-round 6.95; got {prospect['composite_grade']}"
        )
        assert prospect["tier"] == "T3"


class TestFitScoreMultiInputInteraction:
    def _setup_fit_scenario(self):
        """OPEN P2 QB need (base 70); prospect QB with locked report raw 7.00
        scheme_fit 0.90; one RESOLVED HIGH MEDICAL flag (mult 0.8); one OPEN
        LOW CHARACTER flag (deduction 15)."""
        s1 = create_scout(
            level="AREA",
            full_name="Fit Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="Dir One")
        create_roster_need(season_year=2026, position="QB", priority_tier="P2")
        p1 = create_prospect(s1, full_name="Fit Prospect", position="QB", college="State U")
        create_and_lock_report(p1["id"], s1, d1, raw_grade=7.00, scheme_fit=0.90)
        # RESOLVED HIGH MEDICAL flag
        fmed = create_flag(
            p1["id"],
            MED_HEADERS,
            flag_type="MEDICAL",
            severity="HIGH",
            detail="knee repair history",
        )
        resp = api_client.acknowledge_flag(fmed["id"], MED_HEADERS)
        get_success_data(resp)
        resp = api_client.resolve_flag(fmed["id"], {"resolution_note": "cleared with note"}, MED_HEADERS)
        get_success_data(resp)
        # OPEN LOW CHARACTER flag
        create_flag(
            p1["id"],
            area_headers(s1),
            flag_type="CHARACTER",
            severity="LOW",
            detail="missed one meeting",
        )
        advance_prospect(p1["id"], "EVALUATED", d1)
        advance_prospect(p1["id"], "BOARD_READY", d1)
        b1 = create_draft_board(d1, season_year=2026)
        return s1, d1, p1, b1

    def test_fit_score_combines_all_four_inputs(self, api):
        """PRD §3.5: "The fit score is then the base need, multiplied by the
        scheme multiplier, multiplied by the medical multiplier, minus the
        character deduction, clamped into the inclusive range 0.0 to 100.0,
        and rounded half-up to 2 decimal places." With base 70.0 (P2),
        scheme 0.90, med 0.8 (RESOLVED HIGH MEDICAL), deduction 15 (OPEN
        CHARACTER): round2(min(100, max(0, 70*0.9*0.8 - 15))) = 35.40.

        Design: Difficulty/combinatorial_formula/fit_score_multi_input_interaction
        """
        _, d1, p1, b1 = self._setup_fit_scenario()
        entry = add_board_entry(b1["id"], p1["id"], d1)
        assert entry["fit_score"] == pytest.approx(35.40, abs=0.005), (
            f"fit = round2(min(100, max(0, 70*0.9*0.8 - 15))) = 35.40; got "
            f"{entry['fit_score']}"
        )

    def test_flag_status_remains_under_review_with_open_character(self, api):
        """PRD §3.2: "Resolving a flag moves the prospect to `CLEARED` — but
        only when no other flag of that prospect remains in `OPEN`,
        `ACKNOWLEDGED`, or `ESCALATED`; otherwise the prospect stays
        `UNDER_REVIEW`." Here the OPEN CHARACTER flag keeps the prospect
        UNDER_REVIEW even though the MEDICAL flag was resolved.

        Design: Difficulty/combinatorial_formula/fit_score_multi_input_interaction
        """
        _, d1, p1, _ = self._setup_fit_scenario()
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["flag_status"] == "UNDER_REVIEW"
        # composite_grade from the single locked report: 5.0+1.5*(7.00-6.00)/1.00 = 6.50
        assert prospect["composite_grade"] == pytest.approx(6.50, abs=0.005)
        assert prospect["tier"] == "T3"


class TestTierBoundaryInclusive:
    def _setup_tier_pair(self):
        """Scout mean 6.00 stdev 1.50: raw 8.00 -> normalized 7.00 (composite 7.00,
        tier T2); raw 7.99 -> normalized 6.99 (composite 6.99, tier T3)."""
        s1 = create_scout(
            level="AREA",
            full_name="Boundary Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.50,
        )
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="Edge High", position="S", college="State U")
        p2 = create_prospect(s1, full_name="Edge Low", position="S", college="Tech")
        create_and_lock_report(p1["id"], s1, d1, raw_grade=8.00, scheme_fit=1.00)
        create_and_lock_report(p2["id"], s1, d1, raw_grade=7.99, scheme_fit=1.00)
        return s1, d1, p1, p2

    def test_composite_exactly_700_is_t2(self, api):
        """PRD §3.3 step 2: "Tier assignment then maps the composite onto a
        bucket with inclusive lower bounds: 8.00 or above is `T1`, 7.00 up to
        but not including 8.00 is `T2`...Exactly 7.00 is `T2`; 6.99 is `T3`."

        Design: Difficulty/boundary_precision_check/tier_boundary_700_inclusive
        """
        _, d1, p1, _ = self._setup_tier_pair()
        prospect = get_success_data(api_client.get_prospect(p1["id"], director_headers(d1)))
        assert prospect["composite_grade"] == pytest.approx(7.00, abs=0.005)
        assert prospect["tier"] == "T2", (
            f"composite 7.00 is T2 by inclusive-lower-bound rule; got {prospect['tier']}"
        )

    def test_composite_699_is_t3(self, api):
        """PRD §3.3 step 2: "Tier assignment then maps the composite onto a
        bucket with inclusive lower bounds: 8.00 or above is `T1`, 7.00 up to
        but not including 8.00 is `T2`, 6.00 up to but not including 7.00 is
        `T3`, and anything below 6.00 is `T4`. Exactly 7.00 is `T2`; 6.99 is
        `T3`."

        Design: Difficulty/boundary_precision_check/tier_boundary_700_inclusive
        """
        _, d1, _, p2 = self._setup_tier_pair()
        prospect = get_success_data(api_client.get_prospect(p2["id"], director_headers(d1)))
        assert prospect["composite_grade"] == pytest.approx(6.99, abs=0.005)
        assert prospect["tier"] == "T3", (
            f"composite 6.99 is T3 (below the inclusive 7.00 boundary); got {prospect['tier']}"
        )
