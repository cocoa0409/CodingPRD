"""Transitive cascades and outcome reconciliation: the depth-3 session→auth→plan
cascade, reassessment finalization and phase advancement, the reduction-vs-PERV
dual variant, and the adherence-rate calculation.

Queue A: cascade_session_complete_exhaust_hold, cascade_reassessment_finalize_maintenance,
dual_variant_outcome_reduction_vs_perv.
Queue B: adherence_rate_zero_logs_is_zero, adherence_rate_compliant_fraction.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    get_success_data,
    create_adherence_log,
    setup_active_plan_scenario,
    setup_reassessment_scenario,
    setup_exhausted_auth_and_held_plan,
)

CLINICIAN = TEST_USERS["clinician_headers"]
AUTHORIZER = TEST_USERS["authorizer_headers"]


# ---- Queue A: cascade_session_complete_exhaust_hold (>=2 tests) ----

def test_completion_exhausts_authorization_at_cap(api):
    """PRD §3.5: "then (link two, conditional) if visits_used is now greater than or
    equal to visit_cap, the authorization transitions APPROVED → EXHAUSTED."

    Design: Difficulty/transitive_cascade/cascade_session_complete_exhaust_hold
    """
    s = setup_exhausted_auth_and_held_plan()
    auth = s["authorization"]
    assert auth["visits_used"] == 1
    assert auth["visits_remaining"] == 0
    assert auth["status"] == "EXHAUSTED"


def test_completion_cascade_holds_active_plan(api):
    """PRD §3.5: "then (link three, conditional) every ACTIVE plan on that now-exhausted
    authorization transitions to ON_HOLD."

    Design: Difficulty/transitive_cascade/cascade_session_complete_exhaust_hold
    """
    s = setup_exhausted_auth_and_held_plan()
    assert s["session"]["clinical_status"] == "COMPLETED"
    assert s["plan"]["status"] == "ON_HOLD"


# ---- Queue A: cascade_reassessment_finalize_maintenance (>=2 tests) ----

def test_reassessment_finalize_freezes_perv(api):
    """PRD §3.8: "The perv_pct (Percent Excess Volume Reduction) instead measures
    shrinkage of the excess over the contralateral limb, and its denominator is the
    baseline excess rather than the baseline volume."

    Design: Difficulty/transitive_cascade/cascade_reassessment_finalize_maintenance
    """
    s = setup_reassessment_scenario()
    finalized = validate_success(api.finalize_reassessment(s["reassessment"]["id"], CLINICIAN))
    assert finalized["status"] == "FINALIZED"
    assert finalized["perv_pct"] == 70.6


def test_reassessment_finalize_advances_plan_to_maintenance(api):
    """PRD §3.8: "Finalization also carries a phase-advancement side effect: when perv_pct
    is at least 50, the referenced plan's phase advances PHASE_1_INTENSIVE →
    PHASE_2_MAINTENANCE."

    Design: Difficulty/transitive_cascade/cascade_reassessment_finalize_maintenance
    """
    s = setup_reassessment_scenario()
    get_success_data(api.finalize_reassessment(s["reassessment"]["id"], CLINICIAN))
    plan = get_success_data(api.get_treatment_plan(s["plan"]["id"], CLINICIAN))
    assert plan["phase"] == "PHASE_2_MAINTENANCE"


# ---- Queue A: dual_variant_outcome_reduction_vs_perv (>=2 tests) ----

def test_volume_reduction_pct_uses_baseline_volume_denominator(api):
    """PRD §3.8: "The volume_reduction_pct measures shrinkage of the affected limb
    against its own earlier size: it is the baseline evaluation's limb_volume_ml minus
    the current evaluation's limb_volume_ml, divided by the baseline's limb_volume_ml,
    multiplied by 100, rounded to one decimal place."

    Design: Difficulty/dual_variant_calc/dual_variant_outcome_reduction_vs_perv
    """
    s = setup_reassessment_scenario()
    finalized = validate_success(api.finalize_reassessment(s["reassessment"]["id"], CLINICIAN))
    assert finalized["volume_reduction_pct"] == 20.4


def test_perv_pct_uses_baseline_excess_denominator_and_category(api):
    """PRD §3.8: "it is the baseline's excess_volume_ml minus the current's
    excess_volume_ml, divided by the baseline's excess_volume_ml, multiplied by 100,
    rounded to one decimal place — a materially different figure from the volume
    reduction even for identical inputs. The outcome_category is keyed off perv_pct:
    EXCELLENT when it is at least 50."

    Design: Difficulty/dual_variant_calc/dual_variant_outcome_reduction_vs_perv
    """
    s = setup_reassessment_scenario()
    finalized = validate_success(api.finalize_reassessment(s["reassessment"]["id"], CLINICIAN))
    assert finalized["perv_pct"] == 70.6
    assert finalized["outcome_category"] == "EXCELLENT"


# ---- Queue B: adherence rate ----

def test_adherence_rate_zero_with_no_logs(api):
    """PRD §3.8: "when a plan has no logged days the rate is exactly 0.0."

    Design: Corner/calculations/adherence_rate_zero_logs_is_zero
    """
    s = setup_active_plan_scenario()
    plan = get_success_data(api.get_treatment_plan(s["plan"]["id"], CLINICIAN))
    assert plan["adherence_rate"] == 0.0


def test_adherence_rate_compliant_fraction(api):
    """PRD §3.8: "A day counts as compliant when wore_garment is true and
    minutes_completed is greater than or equal to the plan's prescribed_daily_minutes.
    The adherence_rate is the count of compliant days divided by the total number of
    logged days, multiplied by 100 and rounded to one decimal place."

    Design: Corner/calculations/adherence_rate_compliant_fraction
    """
    s = setup_active_plan_scenario(prescribed_daily_minutes=60)
    plan_id = s["plan"]["id"]
    create_adherence_log(plan_id, log_date="2026-06-01", minutes_completed=60, wore_garment=True)
    create_adherence_log(plan_id, log_date="2026-06-02", minutes_completed=30, wore_garment=True)
    create_adherence_log(plan_id, log_date="2026-06-03", minutes_completed=90, wore_garment=False)
    plan = get_success_data(api.get_treatment_plan(plan_id, CLINICIAN))
    assert plan["adherence_rate"] == 33.3
