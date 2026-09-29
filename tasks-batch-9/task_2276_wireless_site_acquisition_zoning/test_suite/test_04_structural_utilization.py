"""Capacity utilization: squared wind, multiplicative ice, code-revision scaling."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_score, ok

UTILIZATION_H = 99.70
UTILIZATION_G = 94.72


def _two_analyses_on_identical_loading(api: ApiClient) -> Dict[str, Any]:
    """One loading case opened twice, once under each TIA-222 revision."""
    chain = S.base_reference_data(api)
    heavy = {
        "existing_load_pct": C.HEAVY_EXISTING_LOAD_PCT,
        "appurtenance_count": C.HEAVY_APPURTENANCE_COUNT,
        "wind_speed_mph": C.HEAVY_WIND_SPEED_MPH,
        "ice_thickness_in": C.HEAVY_ICE_THICKNESS_IN,
    }

    cand_h = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, cand_h["id"])
    cand_g = S.create_candidate(
        api,
        chain["ring_id"],
        chain["ll_id"],
        chain["jur_id"],
        lat=42.3520,
        lon=-71.0630,
        distance_from_center_m=220,
    )
    S.rf_qualify(api, cand_g["id"])

    analysis_h = S.create_analysis(
        api, cand_h["id"], analysis_type=C.TIA_222_H, **heavy
    )
    analysis_g = S.create_analysis(
        api, cand_g["id"], analysis_type=C.TIA_222_G, **heavy
    )
    chain.update(
        {
            "cand_h": cand_h["id"],
            "cand_g": cand_g["id"],
            "sa_h": analysis_h["id"],
            "sa_g": analysis_g["id"],
        }
    )
    return chain


def test_same_loading_case_utilizes_differently_under_each_code_revision(
    api: ApiClient,
) -> None:
    """The code factor scales the whole sum, so one revision passes and one does not.

    PRD: "The proposed load is the sum of a fixed 9.5 percentage points for the new
    antenna array and the appurtenance load, that sum multiplied by the wind factor
    and then by the ice factor."

    PRD: "The wind factor is the ratio of `wind_speed_mph` to a 90-mph baseline,
    squared."

    PRD: "The ice factor is one plus 0.15 for each inch of `ice_thickness_in`."

    PRD: "`capacity_utilization_pct` is the sum of `existing_load_pct` and the
    proposed load, multiplied by the code factor, rounded half up to two decimal
    places — a single rounding at the very end, with every intermediate factor left
    unrounded."

    Design: Difficulty/combinatorial_formula/structural_utilization_nonlinear_wind_ice_code_interaction
    """
    chain = _two_analyses_on_identical_loading(api)

    completed_h = ok(api.complete_structural_analysis(chain["sa_h"], headers=S.analyst()))
    completed_g = ok(api.complete_structural_analysis(chain["sa_g"], headers=S.analyst()))

    assert_score(
        completed_h["capacity_utilization_pct"], UTILIZATION_H, "capacity_utilization_pct"
    )
    assert_score(
        completed_g["capacity_utilization_pct"], UTILIZATION_G, "capacity_utilization_pct"
    )
    assert_fields(completed_h, status="COMPLETED")
    assert_fields(completed_g, status="COMPLETED")


def test_utilization_bands_split_the_two_results_and_their_candidates(
    api: ApiClient,
) -> None:
    """The older revision shaves five points off the same loading without changing the band.

    PRD: "The code factor is 1.00 under `TIA_222_H` and 0.95 under `TIA_222_G`, the
    older revision being the more permissive of the two."

    PRD: "A utilization of 85.00 or less is a `PASS`."

    PRD: "A utilization above 85.00 but no greater than 100.00 is a
    `PASS_WITH_MOD` — the structure can carry the build, but only after
    reinforcement."

    PRD: "A `PASS_WITH_MOD` leaves the candidate in `STRUCTURAL_HOLD`: it takes a
    certified modification design to clear it."

    Design: Difficulty/combinatorial_formula/structural_utilization_nonlinear_wind_ice_code_interaction
    """
    chain = _two_analyses_on_identical_loading(api)

    completed_h = ok(api.complete_structural_analysis(chain["sa_h"], headers=S.analyst()))
    completed_g = ok(api.complete_structural_analysis(chain["sa_g"], headers=S.analyst()))

    assert_score(
        completed_h["capacity_utilization_pct"], UTILIZATION_H, "capacity_utilization_pct"
    )
    assert_score(
        completed_g["capacity_utilization_pct"], UTILIZATION_G, "capacity_utilization_pct"
    )
    assert_fields(completed_h, result="PASS_WITH_MOD")
    assert_fields(completed_g, result="PASS_WITH_MOD")

    candidate_h = ok(api.get_candidate(chain["cand_h"], headers=S.analyst()))
    candidate_g = ok(api.get_candidate(chain["cand_g"], headers=S.analyst()))
    assert_fields(candidate_h, feasibility_status="STRUCTURAL_HOLD")
    assert_fields(candidate_g, feasibility_status="STRUCTURAL_HOLD")
