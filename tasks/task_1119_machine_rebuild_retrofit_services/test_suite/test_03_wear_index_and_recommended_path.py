"""Wear-index computation: weighted scoring, the 1.5 clamp, and the inclusive
recommended-path threshold bands."""

import pytest

import test_helpers as fx


def _assess(api, pd, sr, bl):
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    return fx.create_assessment(
        machine["id"], positioning_deviation_microns=pd,
        spindle_runout_microns=sr, backlash_microns=bl,
    )


class TestWearIndexClamp:
    def test_wear_index_raw_above_cap_is_clamped_to_150(self, api):
        """PRD §3.2: "The positioning deviation is divided by a 20.0-micron reference and given half the total weight; the spindle runout is divided by a 10.0-micron reference and given three-tenths of the weight; the backlash is divided by a 15.0-micron reference and given one-fifth of the weight."
        PRD §3.2: "The three weighted terms are summed, and the raw sum is capped at 1.5 — a raw score above the cap is replaced by the cap itself."
        PRD §3.2: "The capped value is multiplied by 100 and rounded half-up to two decimal places to produce the stored `wear_index`."

        Design: Difficulty/combinatorial_formula/wear_index_weighted_clamp
        """
        assessment = _assess(api, pd=300, sr=200, bl=150)
        # raw = 0.5*15 + 0.3*20 + 0.2*10 = 15.5, capped to 1.5 -> 150.00
        assert assessment["wear_index"] == pytest.approx(150.0, abs=0.001)
        fx.assert_assessment(assessment)

    def test_wear_index_weighted_sum_without_clamp(self, api):
        """PRD §3.2: "The positioning deviation is divided by a 20.0-micron reference and given half the total weight; the spindle runout is divided by a 10.0-micron reference and given three-tenths of the weight; the backlash is divided by a 15.0-micron reference and given one-fifth of the weight."
        PRD §3.2: "The capped value is multiplied by 100 and rounded half-up to two decimal places to produce the stored `wear_index`."

        Design: Difficulty/combinatorial_formula/wear_index_weighted_clamp
        """
        assessment = _assess(api, pd=30, sr=12, bl=9)
        # raw = 0.5*1.5 + 0.3*1.2 + 0.2*0.6 = 1.23 -> 123.00
        assert assessment["wear_index"] == pytest.approx(123.0, abs=0.001)
        assert assessment["recommended_path"] == "FULL_REBUILD"


class TestRecommendedPathBoundaryEighty:
    def test_wear_exactly_80_recommends_full_rebuild(self, api):
        """PRD §3.2: "The `recommended_path` then falls out of fixed thresholds with inclusive boundaries: a `wear_index` of at least 80.00 yields `FULL_REBUILD`; otherwise a `wear_index` of at least 40.00 yields `MECHANICAL_REBUILD`; anything lower yields `RETROFIT_ONLY`."

        Design: Difficulty/boundary_precision_check/wear_index_exactly_80_recommends_full_rebuild
        """
        assessment = _assess(api, pd=16, sr=8, bl=12)
        # raw = 0.5*0.8 + 0.3*0.8 + 0.2*0.8 = 0.8 -> 80.00 exactly
        assert assessment["wear_index"] == pytest.approx(80.0, abs=0.001)
        assert assessment["recommended_path"] == "FULL_REBUILD"

    def test_wear_just_below_80_recommends_mechanical_rebuild(self, api):
        """PRD §3.2: "The `recommended_path` then falls out of fixed thresholds with inclusive boundaries: a `wear_index` of at least 80.00 yields `FULL_REBUILD`; otherwise a `wear_index` of at least 40.00 yields `MECHANICAL_REBUILD`; anything lower yields `RETROFIT_ONLY`."

        Design: Difficulty/boundary_precision_check/wear_index_exactly_80_recommends_full_rebuild
        """
        assessment = _assess(api, pd=15, sr=8, bl=12)
        # raw = 0.5*0.75 + 0.3*0.8 + 0.2*0.8 = 0.775 -> 77.50
        assert assessment["wear_index"] == pytest.approx(77.5, abs=0.001)
        assert assessment["recommended_path"] == "MECHANICAL_REBUILD"


def test_recommended_path_bands_below_full_threshold(api):
    """PRD §3.2: "The `recommended_path` then falls out of fixed thresholds with inclusive boundaries: a `wear_index` of at least 80.00 yields `FULL_REBUILD`; otherwise a `wear_index` of at least 40.00 yields `MECHANICAL_REBUILD`; anything lower yields `RETROFIT_ONLY`."

    Design: Corner/calculations/recommended_path_bands_below_full_threshold
    """
    light = _assess(api, pd=4, sr=2, bl=3)
    # raw = 0.5*0.2 + 0.3*0.2 + 0.2*0.2 = 0.2 -> 20.00
    assert light["wear_index"] == pytest.approx(20.0, abs=0.001)
    assert light["recommended_path"] == "RETROFIT_ONLY"

    edge = _assess(api, pd=16, sr=0, bl=0)
    # raw = 0.5*0.8 = 0.4 -> 40.00 exactly; >= 40.00 boundary is inclusive
    assert edge["wear_index"] == pytest.approx(40.0, abs=0.001)
    assert edge["recommended_path"] == "MECHANICAL_REBUILD"
