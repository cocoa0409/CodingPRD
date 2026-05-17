"""Severity scoring: provisional vs final (dual-variant calculation).

PRD §3.6 defines both variants and explicitly states they produce
different scores on the same critical_flags.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    analyte_spec,
    anchor_clock,
    create_catalog_bundle,
    measurement,
    release,
    resultate,
    walk_order_to_received,
)


# ===========================================================================
# §3.6 Provisional sum-then-round vs final round-per-piece-then-sum
# difficulty: dual_variant_calc /
#             severity_score_provisional_vs_final_on_lab_result
# difficulty: combinatorial_formula /
#             severity_score_final_nested_rounding_order_matters
# ===========================================================================
class TestSeverityScoringDualVariant:
    """Two HIGH-bounded analytes both at value=400, bound=300 yield
    per-analyte distance = abs(400-300)/max(300,1) = 0.333... and
    weight*distance = 0.666... per flag.

    Provisional sum-then-round: raw = 0.6666... + 0.6666... = 1.3333...
    round_half_up to 2 decimal places => 1.33.

    Final round-per-piece-then-sum with historical_factor=1.0 (no
    prior RELEASED critical results): each piece = round_half_up(2 *
    0.333... * 1.0, 2) = 0.67; sum = 0.67 + 0.67 = 1.34.
    """

    def _setup_two_high_analytes(self):
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
                analyte_spec(
                    analyte_code="A2", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        return bundle

    def test_provisional_score_is_1_33_for_two_high_at_400(self, api):
        """PRD §3.6: "The system accumulates, across every entry in
        `critical_flags`, the product of the flag's weight and the
        flag's per-analyte distance into a running raw total. After
        the loop completes, the raw total is rounded once at the very
        end to 2 decimal places using round-half-up. This is the
        sum-then-round ordering."

        Claim: with two HIGH analytes at value=400 and critical_high
        =300, the DRAFT result's severity_score is 1.33.

        # difficulty: dual_variant_calc/severity_score_provisional_vs_final_on_lab_result
        # difficulty: combinatorial_formula/severity_score_final_nested_rounding_order_matters
        """
        bundle = self._setup_two_high_analytes()
        walked = walk_order_to_received(bundle)
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        assert result["status"] == "DRAFT"
        assert result["severity_score"] == pytest.approx(
            1.33, abs=1e-9,
        )

    def test_final_score_is_1_34_after_release_no_history(self, api):
        """PRD §3.6: "Then, for every entry in `critical_flags`, the
        system computes the product of the flag's weight, the flag's
        per-analyte distance, and the historical factor; each such
        per-flag product is independently rounded to 2 decimal places
        using round-half-up to form a per-flag piece. The final score
        is the plain sum of these pieces with no further rounding
        applied. This is the round-then-sum ordering, with a different
        input set than the provisional."

        Claim: after release with no prior RELEASED critical results
        (historical_factor = 1.0), severity_score is 1.34, differing
        from the provisional 1.33.

        # difficulty: dual_variant_calc/severity_score_provisional_vs_final_on_lab_result
        # difficulty: combinatorial_formula/severity_score_final_nested_rounding_order_matters
        """
        bundle = self._setup_two_high_analytes()
        walked = walk_order_to_received(bundle)
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        assert released["status"] == "RELEASED"
        assert released["severity_score"] == pytest.approx(
            1.34, abs=1e-9,
        )


# ===========================================================================
# §3.6 Final historical-factor blend (no-history neutral case)
# ===========================================================================
class TestFinalSeverityHistoricalBlend:

    def test_final_severity_with_no_history_uses_factor_1_0(self, api):
        """PRD §3.6: "the system looks up the two most recently
        released lab results for the same `patient_id` and the same
        `panel_id`, ordered by `released_at` descending, excluding the
        current result itself. From that lookback of up to two prior
        results, the system counts how many had any critical flags,
        multiplies that count by 0.25, adds 1.0, and uses the sum as
        a historical factor."

        Claim: zero prior RELEASED results => historical_factor = 1.0,
        which makes the final score for two HIGH analytes at value 400
        equal 1.34 (matching the no-history case).
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
                analyte_spec(
                    analyte_code="A2", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        assert released["severity_score"] == pytest.approx(
            1.34, abs=1e-9,
        )
