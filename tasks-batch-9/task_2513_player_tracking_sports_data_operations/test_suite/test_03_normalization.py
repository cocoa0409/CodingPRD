"""
Normalized tracking metrics: the same segment values under the two bases, and
the rounding order that separates them.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_two_dp,
    expected_canonical_season_value,
    expected_raw_generation_value,
)
from test_helpers.constants import (
    BASIS_CANONICAL_SEASON,
    BASIS_RAW_GENERATION,
    COLLECTION_COLLECTED,
    MAPPING_VERSION,
    METRIC_SPRINT_DISTANCE,
    METRIC_TOTAL_DISTANCE,
)
from test_helpers.test_users import ENGINEER_HEADERS, OPS_HEADERS

G1_SEGMENTS = [123.456, 78.912, 45.678, 12.345]
G3_SEGMENTS = [10.005, 10.005, 10.005, 10.005]


def _collected_game(
    api: ApiClient,
    tracking_generation: str = "G1",
    tracking_tech: str = "HYBRID",
    modality: str = "UWB_ANCHOR",
    axis_mm: float = 90.0,
) -> fx.World:
    """A game whose collection has been opened and closed, carrying no tags."""
    world = fx.World()
    world.venue = fx.register_venue(api, tracking_tech=tracking_tech)
    rig = fx.deploy_rig(api, world.venue["id"], modality=modality)
    fx.record_run(
        api,
        rig["id"],
        ENGINEER_HEADERS,
        axis_rms_x_mm=axis_mm,
        axis_rms_y_mm=axis_mm,
        axis_rms_z_mm=axis_mm,
    )
    world.rig = fx.certify_rig(api, rig["id"], OPS_HEADERS)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"],
                world.home_club["id"],
                world.away_club["id"],
                tracking_generation=tracking_generation,
            ),
            OPS_HEADERS,
        )
    )
    validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    world.game = validate_success(api.close_collection(world.game["id"], OPS_HEADERS))
    assert world.game["collection_status"] == COLLECTION_COLLECTED
    return world


def _run(api: ApiClient, game_id: str, basis: str, metric_code: str, segments) -> dict:
    return get_success_data(
        api.create_normalization_run(
            game_id,
            fac.normalization_run_payload(
                segment_values=segments, basis=basis, metric_code=metric_code
            ),
            OPS_HEADERS,
        ),
        expected_status=201,
    )


# ---------------------------------------------------------------------------
# The two bases on a G1 game
# ---------------------------------------------------------------------------

def test_raw_generation_rounds_each_segment_before_summing(api, clock):
    """PRD §3.9: "Under the `RAW_GENERATION` basis, no drift correction is applied —
    `drift_correction_pct` is written as 0 — and the value is reproduced the way the
    capturing generation's own pipeline published it: each element of `segment_values`
    is multiplied by the generation scale factor and rounded half up to two decimal
    places, those rounded per-segment figures are added together, and the total is
    rounded half up to two decimal places again."
    PRD §3.9: "`scale_factor_applied` is the generation's scale constant: a `G1` capture
    scales by 1.042, a `G2` capture by 1.017, and a `G3` capture by 1.000, since the
    current generation is the reference."

    Four G1 segments scaled and rounded one by one sum to 271.33.

    The raw basis carries no drift correction at all, whatever the generation.

    Design: Difficulty/dual_variant_calc/normalization_raw_generation_versus_canonical_season_same_segments
    """
    world = _collected_game(api)

    run = _run(
        api, world.game_id, BASIS_RAW_GENERATION, METRIC_TOTAL_DISTANCE, G1_SEGMENTS
    )
    assert_two_dp(run["normalized_value"], 271.33)
    assert_two_dp(run["normalized_value"], expected_raw_generation_value(G1_SEGMENTS, "G1"))
    assert_two_dp(run["scale_factor_applied"], 1.042)
    assert float(run["drift_correction_pct"]) == 0.0
    assert run["source_generation"] == "G1"
    assert run["mapping_version"] == MAPPING_VERSION


def test_canonical_season_sums_exactly_then_applies_the_generation_drift(api, clock):
    """PRD §3.9: "Under the `CANONICAL_SEASON` basis the arithmetic is deliberately
    reversed: the elements of `segment_values` are added together at full precision with
    no intermediate rounding, that exact sum is multiplied once by the generation scale
    factor, the result is then multiplied by one plus the generation's drift correction
    expressed as a fraction — that is, the drift percentage divided by one hundred — and
    only then is the figure rounded half up to two decimal places, exactly once."
    PRD §3.9: "The drift corrections are a reduction of six tenths of one percent for
    `G1` data and two tenths of one percent for `G2` data, and no correction at all for
    `G3` data, so `drift_correction_pct` is written as -0.6, -0.2 and 0.0 respectively."

    The same four segments summed first and drifted by -0.6% give 269.70.

    Design: Difficulty/dual_variant_calc/normalization_raw_generation_versus_canonical_season_same_segments
    """
    world = _collected_game(api)

    run = _run(
        api, world.game_id, BASIS_CANONICAL_SEASON, METRIC_TOTAL_DISTANCE, G1_SEGMENTS
    )
    assert_two_dp(run["normalized_value"], 269.70)
    assert_two_dp(
        run["normalized_value"], expected_canonical_season_value(G1_SEGMENTS, "G1")
    )
    assert_two_dp(run["scale_factor_applied"], 1.042)
    assert_two_dp(run["drift_correction_pct"], -0.6)
    assert run["source_generation"] == "G1"


def test_the_two_bases_differ_by_one_point_six_three_on_identical_input(api, clock):
    """PRD §3.9: "Because of both the reversed rounding order and the drift correction, the
    same `segment_values` yield a strictly different `normalized_value` under the two
    bases for `G1` and `G2` data, and the league relies on that: `RAW_GENERATION` is
    what a historical broadcast graphic must match, and `CANONICAL_SEASON` is what a
    cross-season leaderboard must use."
    PRD §2.7: "A normalization run's `normalized_value` is rounded half up to two
    decimal places."

    Byte-identical segment values, two bases, a 1.63 gap.

    Design: Difficulty/dual_variant_calc/normalization_raw_generation_versus_canonical_season_same_segments
    """
    world = _collected_game(api)

    raw = _run(
        api, world.game_id, BASIS_RAW_GENERATION, METRIC_TOTAL_DISTANCE, G1_SEGMENTS
    )
    canonical = _run(
        api, world.game_id, BASIS_CANONICAL_SEASON, METRIC_TOTAL_DISTANCE, G1_SEGMENTS
    )

    delta = float(raw["normalized_value"]) - float(canonical["normalized_value"])
    assert_two_dp(round(delta, 2), 1.63)
    assert raw["source_generation"] == "G1"
    assert canonical["source_generation"] == "G1"
    assert raw["mapping_version"] == MAPPING_VERSION
    assert canonical["mapping_version"] == MAPPING_VERSION


# ---------------------------------------------------------------------------
# The rounding order isolated on a generation with neutral scale and drift
# ---------------------------------------------------------------------------

def _g3_world(api: ApiClient) -> fx.World:
    return _collected_game(
        api,
        tracking_generation="G3",
        tracking_tech="OPTICAL",
        modality="OPTICAL_CAMERA",
        axis_mm=75.0,
    )


def test_raw_basis_rounds_up_each_g3_segment_and_sums_to_forty_point_zero_four(api, clock):
    """PRD §3.9: "Under the `RAW_GENERATION` basis, no drift correction is applied —
    `drift_correction_pct` is written as 0 — and the value is reproduced the way the
    capturing generation's own pipeline published it: each element of `segment_values`
    is multiplied by the generation scale factor and rounded half up to two decimal
    places, those rounded per-segment figures are added together, and the total is
    rounded half up to two decimal places again."
    PRD §3.9: "Rounding each segment first accumulates a small upward bias, which is
    faithful to how the original pipeline reported."

    Each 10.005 segment rounds half up to 10.01 before the four are summed.

    Design: Difficulty/combinatorial_formula/normalization_rounding_order_isolated_on_generation_g3
    """
    world = _g3_world(api)

    run = _run(
        api, world.game_id, BASIS_RAW_GENERATION, METRIC_SPRINT_DISTANCE, G3_SEGMENTS
    )
    assert_two_dp(run["normalized_value"], 40.04)
    assert_two_dp(run["normalized_value"], expected_raw_generation_value(G3_SEGMENTS, "G3"))
    assert_two_dp(run["scale_factor_applied"], 1.000)
    assert float(run["drift_correction_pct"]) == 0.0


def test_canonical_basis_sums_the_g3_segments_first_and_rounds_once(api, clock):
    """PRD §3.9: "Under the `CANONICAL_SEASON` basis the arithmetic is deliberately
    reversed: the elements of `segment_values` are added together at full precision with
    no intermediate rounding, that exact sum is multiplied once by the generation scale
    factor, the result is then multiplied by one plus the generation's drift correction
    expressed as a fraction — that is, the drift percentage divided by one hundred — and
    only then is the figure rounded half up to two decimal places, exactly once."
    PRD §3.9: "`scale_factor_applied` is the generation's scale constant: a `G1` capture
    scales by 1.042, a `G2` capture by 1.017, and a `G3` capture by 1.000, since the
    current generation is the reference."

    Summing 40.020 exactly and rounding once at the end gives 40.02.

    Design: Difficulty/combinatorial_formula/normalization_rounding_order_isolated_on_generation_g3
    """
    world = _g3_world(api)

    run = _run(
        api, world.game_id, BASIS_CANONICAL_SEASON, METRIC_SPRINT_DISTANCE, G3_SEGMENTS
    )
    assert_two_dp(run["normalized_value"], 40.02)
    assert_two_dp(
        run["normalized_value"], expected_canonical_season_value(G3_SEGMENTS, "G3")
    )
    assert_two_dp(run["scale_factor_applied"], 1.000)
    assert float(run["drift_correction_pct"]) == 0.0


def test_the_g3_gap_is_attributable_to_rounding_order_alone(api, clock):
    """PRD §3.9: "Under the `RAW_GENERATION` basis, no drift correction is applied —
    `drift_correction_pct` is written as 0 — and the value is reproduced the way the
    capturing generation's own pipeline published it: each element of `segment_values`
    is multiplied by the generation scale factor and rounded half up to two decimal
    places, those rounded per-segment figures are added together, and the total is
    rounded half up to two decimal places again."
    PRD §3.9: "Under the `CANONICAL_SEASON` basis the arithmetic is deliberately
    reversed: the elements of `segment_values` are added together at full precision with
    no intermediate rounding, that exact sum is multiplied once by the generation scale
    factor, the result is then multiplied by one plus the generation's drift correction
    expressed as a fraction — that is, the drift percentage divided by one hundred — and
    only then is the figure rounded half up to two decimal places, exactly once."
    PRD §3.9: "The drift corrections are a reduction of six tenths of one percent for
    `G1` data and two tenths of one percent for `G2` data, and no correction at all for
    `G3` data, so `drift_correction_pct` is written as -0.6, -0.2 and 0.0 respectively."

    Same scale, same drift, same segments, and still a 0.02 difference.

    Design: Difficulty/combinatorial_formula/normalization_rounding_order_isolated_on_generation_g3
    """
    world = _g3_world(api)

    raw = _run(
        api, world.game_id, BASIS_RAW_GENERATION, METRIC_SPRINT_DISTANCE, G3_SEGMENTS
    )
    canonical = _run(
        api, world.game_id, BASIS_CANONICAL_SEASON, METRIC_SPRINT_DISTANCE, G3_SEGMENTS
    )

    assert_two_dp(raw["scale_factor_applied"], float(canonical["scale_factor_applied"]))
    assert float(raw["drift_correction_pct"]) == float(canonical["drift_correction_pct"])
    delta = float(raw["normalized_value"]) - float(canonical["normalized_value"])
    assert_two_dp(round(delta, 2), 0.02)
