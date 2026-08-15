"""Measure star banding: dual published/draft bases, round-then-band ordering,
and LOWER_BETTER floor-equality boundaries."""
import pytest

from test_helpers import (
    create_active_measure,
    create_cycle,
    create_draft_set,
    cutpoint_row,
    get_performance,
    lock_performance,
    publish_set,
    report_performance,
    setup_collecting_measure,
    transition_cycle,
    validate_success,
)


def _setup_published_and_draft_scenario():
    """Cycle in CUTPOINT_REVIEW: measure ACTIVE, performance 17/20 LOCKED,
    set P (band_4_floor 0.90) PUBLISHED, set D (band_4_floor 0.85) DRAFT."""
    cycle = create_cycle()
    measure = create_active_measure(cycle["id"], code="BCS",
                                    title="Breast Cancer Screening",
                                    measure_type="PROCESS")
    set_p = create_draft_set(cycle["id"],
                             [cutpoint_row(measure["id"], 0.62, 0.75, 0.90, 0.95)],
                             label="official-2028")
    set_d = create_draft_set(cycle["id"],
                             [cutpoint_row(measure["id"], 0.60, 0.72, 0.85, 0.94)],
                             label="draft-2028")
    transition_cycle(cycle["id"], "DATA_COLLECTION")
    perf = report_performance(cycle["id"], measure["id"], 17, 20)
    lock_performance(perf["id"])
    transition_cycle(cycle["id"], "CUTPOINT_REVIEW")
    publish_set(cycle["id"], set_p["id"])
    return {"cycle_id": cycle["id"], "measure": measure,
            "set_p": set_p, "set_d": set_d, "perf_id": perf["id"]}


class TestPublishedVsDraftBanding:
    def test_same_raw_bands_differently_on_published_and_draft(
            self, api, stars_analyst_headers):
        """PRD §2.7: "The `published_star` is banded from the performance's
        `raw_value` against the cycle's currently `PUBLISHED` cut point set — the
        set the cycle's `published_cutpoint_set_id` points to — and is `null` when
        no set of the cycle is `PUBLISHED` or when `raw_value` is `null`."
        PRD §2.7: "The `draft_star` is banded against the most recently created
        cut point set of the cycle that is in `DRAFT` status at the moment the
        banding trigger runs, and is `null` when no `DRAFT` set exists or
        `raw_value` is `null`."

        Raw 0.85 clears band_4_floor 0.85 on the draft set (star 4) but not
        band_4_floor 0.90 on the published set (star 3).

        Design: Difficulty/dual_variant_calc/published_vs_draft_star_banding
        """
        sc = _setup_published_and_draft_scenario()
        perf = validate_success(api.get_measure_performance(sc["perf_id"],
                                                            stars_analyst_headers))
        assert perf["raw_value"] == pytest.approx(0.85)
        assert perf["published_star"] == 3, (
            f"0.85 vs published floors 0.62/0.75/0.90/0.95 bands to 3, got "
            f"{perf['published_star']}"
        )
        assert perf["draft_star"] == 4, (
            f"0.85 vs draft floors 0.60/0.72/0.85/0.94 bands to 4, got "
            f"{perf['draft_star']}"
        )
        assert perf["published_star"] != perf["draft_star"]

    def test_published_star_null_until_a_set_is_published(
            self, api, stars_analyst_headers):
        """PRD §2.7: "The `published_star` is banded from the performance's
        `raw_value` against the cycle's currently `PUBLISHED` cut point set — the
        set the cycle's `published_cutpoint_set_id` points to — and is `null` when
        no set of the cycle is `PUBLISHED` or when `raw_value` is `null`."
        PRD §2.7: "The `draft_star` is banded against the most recently created
        cut point set of the cycle that is in `DRAFT` status at the moment the
        banding trigger runs, and is `null` when no `DRAFT` set exists or
        `raw_value` is `null`."

        Design: Difficulty/dual_variant_calc/published_vs_draft_star_banding
        """
        cycle = create_cycle()
        measure = create_active_measure(cycle["id"], code="BCS",
                                        title="Breast Cancer Screening",
                                        measure_type="PROCESS")
        set_p = create_draft_set(
            cycle["id"], [cutpoint_row(measure["id"], 0.62, 0.75, 0.90, 0.95)],
            label="official-2028")
        create_draft_set(cycle["id"],
                         [cutpoint_row(measure["id"], 0.60, 0.72, 0.85, 0.94)],
                         label="draft-2028")
        transition_cycle(cycle["id"], "DATA_COLLECTION")
        perf = report_performance(cycle["id"], measure["id"], 17, 20)
        lock_performance(perf["id"])

        pre = validate_success(api.get_measure_performance(perf["id"],
                                                           stars_analyst_headers))
        assert pre["published_star"] is None, (
            "published_star is null while no set of the cycle is PUBLISHED"
        )
        assert pre["draft_star"] == 4, (
            "draft_star bands against the most recently created DRAFT set"
        )

        transition_cycle(cycle["id"], "CUTPOINT_REVIEW")
        publish_set(cycle["id"], set_p["id"])

        post = validate_success(api.get_measure_performance(perf["id"],
                                                            stars_analyst_headers))
        assert post["published_star"] == 3
        assert post["draft_star"] == 4, (
            "Publish recomputes published_star; the draft basis is untouched"
        )


class TestRoundThenBand:
    def test_raw_value_rounded_half_up_to_two_decimals(
            self, api, stars_analyst_headers):
        """PRD §3.2: "The `raw_value` is the `numerator` divided by the
        `denominator`, rounded half up to 2 decimal places; when the `denominator`
        is 0, `raw_value` is `null` and both stars are `null`."
        PRD §2.7: "Banding applies to the **rounded** `raw_value`, never the
        unrounded ratio."

        2123 / 2500 = 0.8492 rounds to 0.85 before banding.

        Design: Difficulty/combinatorial_formula/round_then_band_ordering_pinned
        """
        sc = setup_collecting_measure(
            performance=False,
            measure_kwargs={"code": "SPD", "title": "Statin Adherence",
                            "domain": "DRUG_SAFETY", "measure_type": "OUTCOME",
                            "data_source": "PHARMACY_PDE"},
            floors=(0.70, 0.78, 0.85, 0.92))
        perf = report_performance(sc["cycle"]["id"], sc["measure"]["id"],
                                  2123, 2500)
        perf = validate_success(api.get_measure_performance(perf["id"],
                                                            stars_analyst_headers))
        assert perf["raw_value"] == pytest.approx(0.85), (
            f"2123/2500 = 0.8492 must round half up to 0.85, got {perf['raw_value']}"
        )
        assert perf["draft_star"] == 4, (
            "The rounded 0.85 meets band_4_floor 0.85; banding the unrounded "
            "0.8492 would yield 3"
        )

    def test_banding_applies_to_rounded_value_and_published_null(
            self, api, stars_analyst_headers):
        """PRD §2.7: "Banding applies to the **rounded** `raw_value`, never the
        unrounded ratio."
        PRD §2.7: "The `published_star` is banded from the performance's
        `raw_value` against the cycle's currently `PUBLISHED` cut point set — the
        set the cycle's `published_cutpoint_set_id` points to — and is `null` when
        no set of the cycle is `PUBLISHED` or when `raw_value` is `null`."

        849 / 1000 = 0.849 also rounds to 0.85 and clears the 0.85 floor;
        published_star stays null with no PUBLISHED set.

        Design: Difficulty/combinatorial_formula/round_then_band_ordering_pinned
        """
        sc = setup_collecting_measure(
            performance=False,
            measure_kwargs={"code": "SPD", "title": "Statin Adherence",
                            "domain": "DRUG_SAFETY", "measure_type": "OUTCOME",
                            "data_source": "PHARMACY_PDE"},
            floors=(0.70, 0.78, 0.85, 0.92))
        perf = report_performance(sc["cycle"]["id"], sc["measure"]["id"], 849, 1000)
        perf = validate_success(api.get_measure_performance(perf["id"],
                                                            stars_analyst_headers))
        assert perf["raw_value"] == pytest.approx(0.85)
        assert perf["draft_star"] == 4
        assert perf["published_star"] is None


class TestLowerBetterBoundary:
    def test_raw_equal_to_floor_earns_higher_star(self, api, stars_analyst_headers):
        """PRD §2.7: "For a `LOWER_BETTER` measure, the star is 1 plus the count of
        floors that the rounded `raw_value` is less than or equal to."
        PRD §2.7: "A `raw_value` exactly equal to a floor counts toward the higher
        star in both directions."

        Raw 0.50 equals band_4_floor 0.50 on a LOWER_BETTER measure: the star is
        1 + count(0.50 <= f for f in 1.50/0.90/0.50/0.20) = 1 + 3 = 4.

        Design: Difficulty/boundary_precision_check/lower_better_cutpoint_equality_boundary
        """
        sc = setup_collecting_measure(
            performance=False,
            measure_kwargs={"code": "CMP", "title": "Complaints Rate",
                            "domain": "MEMBER_COMPLAINTS", "measure_type": "OUTCOME",
                            "direction": "LOWER_BETTER", "data_source": "COMPLAINTS"},
            floors=(1.50, 0.90, 0.50, 0.20))
        perf = report_performance(sc["cycle"]["id"], sc["measure"]["id"], 10, 20)
        perf = validate_success(api.get_measure_performance(perf["id"],
                                                            stars_analyst_headers))
        assert perf["raw_value"] == pytest.approx(0.5)
        assert perf["draft_star"] == 4, (
            f"raw_value equal to the floor counts toward the higher star; got "
            f"{perf['draft_star']}"
        )

    def test_raw_just_above_floor_drops_a_star(self, api, stars_analyst_headers):
        """PRD §2.7: "For a `LOWER_BETTER` measure, the star is 1 plus the count of
        floors that the rounded `raw_value` is less than or equal to."

        Raw 0.51 is strictly above band_4_floor 0.50 on a LOWER_BETTER measure:
        the star is 1 + count(0.51 <= f for f in 1.50/0.90/0.50/0.20) = 1 + 2 = 3.

        Design: Difficulty/boundary_precision_check/lower_better_cutpoint_equality_boundary
        """
        sc = setup_collecting_measure(
            performance=False,
            measure_kwargs={"code": "CMP", "title": "Complaints Rate",
                            "domain": "MEMBER_COMPLAINTS", "measure_type": "OUTCOME",
                            "direction": "LOWER_BETTER", "data_source": "COMPLAINTS"},
            floors=(1.50, 0.90, 0.50, 0.20))
        perf = report_performance(sc["cycle"]["id"], sc["measure"]["id"], 51, 100)
        perf = validate_success(api.get_measure_performance(perf["id"],
                                                            stars_analyst_headers))
        assert perf["raw_value"] == pytest.approx(0.51)
        assert perf["draft_star"] == 3, (
            f"0.51 misses the 0.50 floor (<=, not <), so the star drops to 3; got "
            f"{perf['draft_star']}"
        )
