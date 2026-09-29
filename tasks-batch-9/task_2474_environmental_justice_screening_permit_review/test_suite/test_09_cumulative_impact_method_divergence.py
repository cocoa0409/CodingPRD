"""The two cumulative impact methodologies over one identical file.

`SCREENING_LEVEL` weights the whole proposed increment while `REFINED` attenuates
it, so the same area and the same application yield two different indices, two
different disproportionate findings, and one superseded row.
"""

from test_helpers import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_SUPERSEDED,
    CONFIDENCE_HIGH,
    METHOD_REFINED,
    METHOD_SCREENING_LEVEL,
    add_assessment,
    assert_amount,
    assert_amounts,
    assert_field,
    assert_fields,
    assert_ratio,
    find_assessment,
    read_application,
    read_area,
)


class TestScreeningLevelMethodology:
    """PRD §3.3 pins the screening-level exposure factor at 1.0000."""

    def test_screening_level_weights_the_whole_increment_and_flags_it(
        self, api, app_a_screening_assessment
    ):
        """80.00 tpy against a 400.00 tpy baseline drives the index to 81.82.

        PRD §3.3: "First, the assessment snapshots the area's current statewide
        screening score into `baseline_burden_score`." and "Second,
        `proposed_increment_pct` is the application's `proposed_emissions_tpy`
        divided by the area's `baseline_load_tpy`, multiplied by 100, rounded half up
        to two decimals." and "Third, `exposure_factor` is determined by method: for
        `SCREENING_LEVEL` it is pinned at exactly 1.0000, so the full proposed
        increment is weighted; for `REFINED` a distance decay is chosen first — 1.00
        when `receptor_distance_m` is at most 300 metres, otherwise 0.75 when it is
        at most 800 metres, otherwise 0.50 — and `exposure_factor` is
        `dispersion_factor` multiplied by that decay, rounded half up to four
        decimals." and "Fourth, the weighted increment is `proposed_increment_pct`
        multiplied by `exposure_factor` multiplied by 1.50, rounded half up to two
        decimals." and "Fifth, the pre-clamp index is `baseline_burden_score`
        multiplied by 0.70, plus the weighted increment, rounded half up to two
        decimals."
        PRD §3.3: "`disproportionate_flag` is true when `cumulative_impact_index` is
        **at least 70.00**."
        PRD §3.3: "`SCREENING_LEVEL` is the default methodology and needs no
        modelling inputs." and "Both fields default to null and stay null for a
        screening-level assessment." and "the assessment lands in `status` `DRAFT`."

        Design: Difficulty/dual_variant_calc/cumulative_impact_screening_vs_refined_divergence
        """
        state = app_a_screening_assessment
        area = read_area(api, state["area_id"])
        assert_amount(area.get("baseline_load_tpy"), 400.00, "baseline_load_tpy")
        assert_amount(
            area.get("ej_screen_score_statewide"), 74.03, "ej_screen_score_statewide"
        )

        screening = find_assessment(api, state["app_id"], state["assessment_id"])

        assert_fields(
            screening,
            {
                "method": METHOD_SCREENING_LEVEL,
                "status": ASSESSMENT_DRAFT,
                "disproportionate_flag": True,
                "dispersion_factor": None,
                "receptor_distance_m": None,
            },
        )
        assert_ratio(screening.get("exposure_factor"), 1.0000, "exposure_factor")
        assert_amounts(
            screening,
            {
                "baseline_burden_score": 74.03,
                # 80.00 / 400.00 x 100 = 20.00 per cent of the existing load.
                "proposed_increment_pct": 20.00,
                # 74.03 x 0.70 = 51.82, plus 20.00 x 1.0000 x 1.50 = 30.00.
                "cumulative_impact_index": 81.82,
            },
        )

        application = read_application(api, state["app_id"])
        assert_amounts(
            application,
            {
                "pre_mitigation_index": 81.82,
                "residual_impact_index": 81.82,
            },
        )

    def test_a_second_assessment_supersedes_the_draft_it_replaces(
        self, api, app_a_screening_assessment
    ):
        """The refined row takes over the file and the draft row is retired.

        PRD §3.3: "Creating a new assessment for an application that already has one
        in `DRAFT` or `RETURNED` moves that older row `DRAFT → SUPERSEDED` or
        `RETURNED → SUPERSEDED` and increments its `version` by 1; the new row then
        rewrites the application's `pre_mitigation_index` and
        `residual_impact_index`, increments the application's `version` by 1, and
        stamps `application_version_after`."
        PRD §3.3: "Candidates are the application's assessments whose `status` is
        `ACCEPTED`, `DRAFT`, `SUBMITTED_FOR_QA` or `RETURNED`; rows in `SUPERSEDED`,
        `INVALIDATED` or `VOIDED` are never candidates."

        Design: Difficulty/dual_variant_calc/cumulative_impact_screening_vs_refined_divergence
        """
        state = app_a_screening_assessment
        screening_id = state["assessment_id"]

        add_assessment(
            api,
            state,
            method=METHOD_REFINED,
            dispersion_factor=0.60,
            receptor_distance_m=500,
        )

        superseded = find_assessment(api, state["app_id"], screening_id)
        assert_field(superseded, "status", ASSESSMENT_SUPERSEDED)
        assert_field(superseded, "method", METHOD_SCREENING_LEVEL)
        # The retired row keeps the number it computed; only its status moved.
        assert_amount(
            superseded.get("cumulative_impact_index"), 81.82, "cumulative_impact_index"
        )

        refined = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_field(refined, "status", ASSESSMENT_DRAFT)
        assert_field(refined, "method", METHOD_REFINED)

        # The governing row is now the refined one, so the file reads 65.32.
        application = read_application(api, state["app_id"])
        assert_amounts(
            application,
            {
                "pre_mitigation_index": 65.32,
                "residual_impact_index": 65.32,
            },
        )


class TestRefinedMethodology:
    """PRD §3.3 attenuates the increment when modelling has been submitted."""

    def test_refined_attenuation_lowers_the_index_and_clears_the_flag(
        self, api, app_a_screening_assessment
    ):
        """A 0.60 dispersion at 500 m gives exposure 0.4500 and an index of 65.32.

        PRD §3.3: "`REFINED` is used when dispersion modelling has been submitted,
        and it requires **both** `dispersion_factor` (a modelled attenuation between
        0.10 and 1.00 inclusive) and `receptor_distance_m` (the whole number of
        metres to the nearest sensitive receptor, at least 0); a refined assessment
        missing either input is refused with `ERR_REFINED_INPUTS_REQUIRED`."
        PRD §3.3: "for `REFINED` a distance decay is chosen first — 1.00 when
        `receptor_distance_m` is at most 300 metres, otherwise 0.75 when it is at
        most 800 metres, otherwise 0.50 — and `exposure_factor` is
        `dispersion_factor` multiplied by that decay, rounded half up to four
        decimals."
        PRD §3.3: "`data_confidence` is `LOW` when the area has no qualifying
        indicators at all — an `active_indicator_count` of 0 — or when the area's
        `data_status` is `STALE`; otherwise it is `HIGH`."
        PRD §3.3: "Because the refined variant attenuates the increment, identical
        application and area inputs yield a strictly lower index under `REFINED` than
        under `SCREENING_LEVEL`, and the refined variant can flip a disproportionate
        finding from true to false."

        Design: Difficulty/dual_variant_calc/cumulative_impact_screening_vs_refined_divergence
        """
        state = app_a_screening_assessment
        screening_id = state["assessment_id"]

        add_assessment(
            api,
            state,
            method=METHOD_REFINED,
            dispersion_factor=0.60,
            receptor_distance_m=500,
        )

        refined = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_fields(
            refined,
            {
                "method": METHOD_REFINED,
                "receptor_distance_m": 500,
                "disproportionate_flag": False,
                "data_confidence": CONFIDENCE_HIGH,
            },
        )
        # 500 m takes the 0.75 decay, so 0.60 x 0.75 = 0.4500.
        assert_ratio(refined.get("exposure_factor"), 0.4500, "exposure_factor")
        assert_amounts(
            refined,
            {
                "baseline_burden_score": 74.03,
                "proposed_increment_pct": 20.00,
                # 51.82 plus 20.00 x 0.4500 x 1.50 = 13.50.
                "cumulative_impact_index": 65.32,
            },
        )

        screening = find_assessment(api, state["app_id"], screening_id)
        divergence = (
            screening["cumulative_impact_index"] - refined["cumulative_impact_index"]
        )
        assert_amount(divergence, 16.50, "screening minus refined index divergence")
        assert refined["cumulative_impact_index"] < screening["cumulative_impact_index"], (
            "the refined index should be strictly lower than the screening index"
        )
        assert screening["disproportionate_flag"] is True, (
            "the screening-level row should still carry its disproportionate finding"
        )

    def test_the_refined_index_is_what_the_application_carries(
        self, api, app_a_screening_assessment
    ):
        """The governing row's index is copied onto the file with no re-rounding.

        PRD §3.3: "Candidates are ranked with `ACCEPTED` ahead of all three of the
        in-progress statuses, and within a rank by `created_at` descending — newest
        first — with a final tie broken by `version` descending." and "The first row
        under that ordering governs." and "The governing assessment supplies
        `pre_mitigation_index` by direct copy of its `cumulative_impact_index`, with
        no re-rounding."

        Design: Difficulty/dual_variant_calc/cumulative_impact_screening_vs_refined_divergence
        """
        state = app_a_screening_assessment
        add_assessment(
            api,
            state,
            method=METHOD_REFINED,
            dispersion_factor=0.60,
            receptor_distance_m=500,
        )

        refined = find_assessment(api, state["app_id"], state["assessment_id"])
        application = read_application(api, state["app_id"])

        assert application["pre_mitigation_index"] == refined["cumulative_impact_index"], (
            "the application should carry the governing assessment's index verbatim"
        )
        assert_amounts(
            application,
            {
                "pre_mitigation_index": 65.32,
                # No conditions exist yet, so the residual equals the pre-mitigation
                # index rather than being reduced.
                "residual_impact_index": 65.32,
                "total_mitigation_credit_tpy": 0.00,
            },
        )
