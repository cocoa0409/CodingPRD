"""Six-minute-walk outcome: provisional (DRAFT) vs verified (FINALIZED) improvement.

Queue A (Difficulty): dual_variant_calc on the clinical-outcome domain.
"""
import pytest

from test_helpers import validate_success
from test_helpers import factories as F
from test_helpers import fixtures as X


def test_six_minute_walk_provisional_then_verified_after_correction(api):
    """PRD §3.6: "The `improvement_meters` is the discharge distance minus the baseline
    distance, and `improvement_pct` is that same difference divided by the baseline
    distance, multiplied by 100, and rounded half up to one decimal place."
    PRD §3.6: "While the discharge assessment is still `DRAFT`, the provisional
    improvement uses the draft `distance_meters` (against the finalized baseline
    distance) and reflects an un-verified value that may still be corrected. Once the
    discharge assessment is `FINALIZED`, the verified improvement uses the
    possibly-corrected `final_distance_meters`, and its `improvement_meters` and
    `improvement_pct` may differ from the provisional figures."

    Design: Difficulty/dual_variant_calc/six_minute_walk_provisional_vs_verified_improvement
    """
    ctx = X.setup_active_program(api, baseline_distance=300)
    disch = validate_success(
        api.create_outcome(F.create_outcome_payload(ctx["program_id"], "DISCHARGE", 360), ctx["clin_headers"]),
        expected_status=201,
    )
    # Provisional read while still DRAFT: 360 vs 300 -> +60m / 20.0%
    provisional = validate_success(api.get_outcome(disch["id"], ctx["clin_headers"]))
    assert provisional["status"] == "DRAFT"
    assert provisional["improvement_meters"] == 60
    assert provisional["improvement_pct"] == pytest.approx(20.0, abs=0.001)

    # Finalize with a corrected distance 345 -> +45m / 15.0%
    validate_success(api.finalize_outcome(disch["id"], {"final_distance_meters": 345}, ctx["clin_headers"]))
    verified = validate_success(api.get_outcome(disch["id"], ctx["clin_headers"]))
    assert verified["status"] == "FINALIZED"
    assert verified["improvement_meters"] == 45
    assert verified["improvement_pct"] == pytest.approx(15.0, abs=0.001)


def test_six_minute_walk_verified_matches_provisional_when_uncorrected(api):
    """PRD §3.6: "Finalizing it moves it from `DRAFT` to `FINALIZED` and may optionally
    correct the distance via `final_distance_meters` supplied at finalize."
    PRD §3.6: "The `improvement_meters` is the discharge distance minus the baseline
    distance, and `improvement_pct` is that same difference divided by the baseline
    distance, multiplied by 100, and rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/six_minute_walk_provisional_vs_verified_improvement
    """
    ctx = X.setup_active_program(api, baseline_distance=300)
    disch = validate_success(
        api.create_outcome(F.create_outcome_payload(ctx["program_id"], "DISCHARGE", 360), ctx["clin_headers"]),
        expected_status=201,
    )
    # Finalize with no correction -> verified uses draft distance 360 unchanged
    validate_success(api.finalize_outcome(disch["id"], {}, ctx["clin_headers"]))
    verified = validate_success(api.get_outcome(disch["id"], ctx["clin_headers"]))
    assert verified["status"] == "FINALIZED"
    assert verified["improvement_meters"] == 60
    assert verified["improvement_pct"] == pytest.approx(20.0, abs=0.001)
