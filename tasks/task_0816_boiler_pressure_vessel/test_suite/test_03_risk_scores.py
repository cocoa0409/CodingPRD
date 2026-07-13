"""The two vessel risk scores: STANDARD vs FORECAST divergence, and the non-linear
clamped score with the suspended-penalty branch.

Difficulty queue A: dual_variant_calc (risk), combinatorial_formula (risk).
"""
from test_helpers import (
    validate_success,
    setup_registered_vessel, setup_certified_vessel,
    new_inspection, raise_deficiency, record_result,
    new_repair_order, complete_repair_order, file_incident, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / risk_standard_vs_forecast_diverge_on_vessel_domain
# ---------------------------------------------------------------------------
def _vessel_with_reinspection_critical():
    """POWER_BOILER installed 2016-01-01 (age 10 -> tier 10) with one CRITICAL
    deficiency driven to REINSPECTION via a completed repair order; clock 2026-06-01."""
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER",
                                  mawp_psig=120, installed_at="2016-01-01T00:00:00Z")
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="CRITICAL", description="cracked weld seam")
    record_result(insp1["id"], ctx["insp_a_id"], "FAIL")
    ro1 = new_repair_order(ctx["vessel_id"], [d1["id"]], ctx["owner_id"], description="reweld seam")
    complete_repair_order(ro1["id"], ctx["owner_id"])
    return ctx


def test_standard_excludes_reinspection_forecast_includes(api):
    """PRD §3.9: "The STANDARD score, stored in `risk_score_standard`, counts only
    deficiencies in `OPEN` or `UNDER_REPAIR` and excludes those in `REINSPECTION` — it
    reflects currently-realized open work. The FORECAST score, stored in
    `risk_score_forecast`, counts deficiencies in `OPEN`, `UNDER_REPAIR`, and
    `REINSPECTION` at full weight — it is the forward-looking view".

    Design: Difficulty/dual_variant_calc/risk_standard_vs_forecast_diverge_on_vessel_domain
    """
    ctx = _vessel_with_reinspection_critical()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["risk_score_standard"] == 40
    assert data["risk_score_forecast"] == 48


def test_forecast_exceeds_standard_mid_reinspection(api):
    """PRD §3.9: "so a vessel mid-reinspection scores higher under FORECAST than under
    STANDARD. This is why completing a repair order (which moves deficiencies into
    `REINSPECTION`) drops the standard score while leaving the forecast score unchanged."

    Design: Difficulty/dual_variant_calc/risk_standard_vs_forecast_diverge_on_vessel_domain
    """
    ctx = _vessel_with_reinspection_critical()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["risk_score_forecast"] > data["risk_score_standard"]


# ---------------------------------------------------------------------------
# combinatorial_formula / risk_nonlinear_clamped_with_suspended_conditional_mode_a
# ---------------------------------------------------------------------------
def _suspended_old_vessel():
    """POWER_BOILER installed 1990-01-01 (age 36 -> tier 35), certified IN_SERVICE
    (PASS, clean_bonus 10), then a CRITICAL incident suspends it (+40) and adds one
    incident penalty (25); clock 2026-06-01."""
    ctx = setup_certified_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER",
                                 mawp_psig=120, installed_at="1990-01-01T00:00:00Z")
    file_incident(ctx["vessel_id"], ctx["owner_id"], severity="CRITICAL",
                  occurred_at="2026-05-15T00:00:00Z", narrative="tube rupture")
    return ctx


def test_critical_incident_suspends_vessel(api):
    """PRD §3.8: "A `CRITICAL` incident, however, is an emergency and triggers a
    coordinated cascade, provided the vessel's `service_status` is `IN_SERVICE` or
    `RESTRICTED`: 1. The vessel's `service_status` advances to `SUSPENDED`."

    Design: Difficulty/combinatorial_formula/risk_nonlinear_clamped_with_suspended_conditional_mode_a
    """
    ctx = _suspended_old_vessel()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["service_status"] == "SUSPENDED"


def test_risk_score_clamped_to_100_with_suspended_penalty(api):
    """PRD §3.9: "If the vessel's `service_status` is `SUSPENDED`, a further penalty of
    40 is added."
    PRD §3.9: "The running total — base plus age factor plus deficiency weight plus
    incident penalty, minus the clean bonus, plus the suspended penalty where applicable
    — is then clamped so that anything below 0 becomes 0 and anything above 100 becomes
    100, yielding the stored integer."

    Design: Difficulty/combinatorial_formula/risk_nonlinear_clamped_with_suspended_conditional_mode_a
    """
    ctx = _suspended_old_vessel()
    data = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    assert data["risk_score_standard"] == 100
