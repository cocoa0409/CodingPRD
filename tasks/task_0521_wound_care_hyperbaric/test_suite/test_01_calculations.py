"""Calculation tests: wound area/severity, supply reimbursement, healing
trajectory, HBO coverage cost. All values pinned to PRD §3.3, §3.4, §3.6, §3.8.
"""
import pytest

from test_helpers import (
    validate_success,
    fixtures,
    factories,
    make_wound_clinician_headers,
    make_hyperbaric_tech_headers,
)


# =============================================================================
# wound_severity_score — combinatorial nonlinear formula (PRD §3.3)
# =============================================================================

def test_severity_score_stage3_infected_necrotic_large_area(api):
    """PRD §3.3: "The raw score is the stage points multiplied by the area
    multiplier, plus 5 if the wound is infected (and 0 otherwise), plus the
    tissue bonus. That raw value is rounded half up to a whole number and then
    clamped so that it is never below a floor of 1 and never above a ceiling of
    100."
    PRD §3.3: "STAGE_3 contributes 4" and "an area strictly greater than 16
    square centimeters gives 2.0" and "NECROTIC contributes 4".
    STAGE_3 (4) * 2.0x (area 20) + 5 infected + 4 NECROTIC == 17.

    Design: Difficulty/combinatorial_formula/severity_score_tiered_nonlinear
    """
    base = fixtures.setup_center_staff_patient(mrn="M3")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(
            base["patient_id"], stage="STAGE_3", length_cm=5, width_cm=4,
            tissue_type="NECROTIC", infected=True),
        make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp, 201)
    assert data["area_cm2"] == 20.0, f"expected area 20.0, got {data['area_cm2']}"
    assert data["severity_score"] == 17, f"expected severity 17, got {data['severity_score']}"


def test_severity_score_area_multiplier_selection(api):
    """PRD §3.3: "an area of at most 4 square centimeters gives a multiplier of
    1.0; an area greater than 4 but at most 16 square centimeters gives 1.5; and
    an area strictly greater than 16 square centimeters gives 2.0".
    A STAGE_2 (2) 2x2 area-4 GRANULATION uses 1.0x -> raw 2 -> severity 2.

    Design: Difficulty/combinatorial_formula/severity_score_tiered_nonlinear
    """
    base = fixtures.setup_center_staff_patient(mrn="M3b")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(
            base["patient_id"], stage="STAGE_2", length_cm=2, width_cm=2,
            tissue_type="GRANULATION"),
        make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp, 201)
    assert data["area_cm2"] == 4.0
    assert data["severity_score"] == 2, f"expected severity 2, got {data['severity_score']}"


# =============================================================================
# wound_severity_score — area-tier boundary at 16 (PRD §3.3)
# =============================================================================

def test_area_tier_boundary_16_inclusive_uses_1_5x(api):
    """PRD §3.3: "an area of exactly 16 uses 1.5 while an area just above 16 uses
    2.0". A STAGE_4 (8) 4x4 area-16 GRANULATION uses 1.5x -> raw 12 -> severity 12.

    Design: Difficulty/boundary_precision_check/area_tier_boundary_16_vs_16plus
    """
    base = fixtures.setup_center_staff_patient(mrn="M11")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(
            base["patient_id"], stage="STAGE_4", length_cm=4, width_cm=4,
            tissue_type="GRANULATION"),
        make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp, 201)
    assert data["area_cm2"] == 16.0
    assert data["severity_score"] == 12, f"expected severity 12, got {data['severity_score']}"


def test_area_tier_boundary_just_above_16_uses_2x(api):
    """PRD §3.3: "an area strictly greater than 16 square centimeters gives 2.0
    — so an area of exactly 16 uses 1.5 while an area just above 16 uses 2.0".
    A STAGE_4 (8) 4.1x4 area-16.4 GRANULATION crosses to 2.0x -> raw 16 -> severity 16.

    Design: Difficulty/boundary_precision_check/area_tier_boundary_16_vs_16plus
    """
    base = fixtures.setup_center_staff_patient(mrn="M11b")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(
            base["patient_id"], stage="STAGE_4", length_cm=4.1, width_cm=4,
            tissue_type="GRANULATION"),
        make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp, 201)
    assert data["area_cm2"] == 16.4
    assert data["severity_score"] == 16, f"expected severity 16, got {data['severity_score']}"


# =============================================================================
# supply_reimbursement — per-line-then-sum rounding order (PRD §3.6)
# =============================================================================

def test_supply_reimbursement_rounds_per_line_then_sums(api):
    """PRD §3.6: "For each line, the covered amount is that line's
    unit_price_cents multiplied by its qty multiplied by its coverage_rate,
    rounded half up to whole cents. The order's covered_cents is the sum of those
    per-line rounded amounts — the rounding happens per line first and the
    whole-cent results are then summed, never the reverse."
    Three lines of 101*1*0.5 == 50.5 -> 51 each -> covered_cents 153 (not 152).

    Design: Difficulty/combinatorial_formula/supply_reimbursement_round_per_line_then_sum
    """
    base = fixtures.setup_draft_plan(budget_cents=500000, mrn="M4")
    version = fixtures.get_plan_version(base["plan_id"], make_wound_clinician_headers(base["wc_id"]))
    resp = api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], version, supply_kind="ADVANCED_DRESSING",
            line_items=factories.THREE_LINES_153),
        make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp, 201)
    assert data["covered_cents"] == 153, f"expected 153, got {data['covered_cents']}"


def test_supply_reimbursement_reflected_in_provisional_covered_cents(api):
    """PRD §3.6: "On acceptance, the order's covered_cents is added to the plan's
    provisional_covered_cents". After submitting one 153c order, the plan's
    provisional_covered_cents equals 153.

    Design: Difficulty/combinatorial_formula/supply_reimbursement_round_per_line_then_sum
    """
    base = fixtures.setup_draft_plan(budget_cents=500000, mrn="M4b")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    version = fixtures.get_plan_version(base["plan_id"], wc_headers)
    api.create_supply_order(
        factories.create_supply_order_payload(
            base["plan_id"], version, line_items=factories.THREE_LINES_153),
        wc_headers)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 153, \
        f"expected 153, got {plan['provisional_covered_cents']}"


# =============================================================================
# healing_trajectory — actual vs projected divergence (PRD §3.4)
# =============================================================================

def _build_three_assessment_plan(api, mrn):
    """Baseline 5x4=20 @ 05-01, 5x3=15 @ 05-08, 4x3=12 @ 05-15; plan ACTIVE."""
    base = fixtures.setup_center_staff_patient(mrn=mrn)
    wc_id = base["wc_id"]
    fixtures.set_clock(base["center_id"], "2026-05-01T00:00:00Z", wc_id)
    asm1 = fixtures.record_assessment(base["patient_id"], wc_id, stage="STAGE_3",
                                      length_cm=5, width_cm=4, tissue_type="GRANULATION")
    # referral accept requires an assessment on file (satisfied above)
    ref = validate_success(api.create_referral(
        factories.create_referral_payload(base["patient_id"]),
        fixtures.INTAKE), 201)
    validate_success(api.accept_referral(ref["id"], fixtures.INTAKE))
    plan = fixtures.create_draft_plan(base["patient_id"], wc_id, asm1["id"],
                                      budget_cents=500000)
    fixtures.activate_plan(plan["id"], wc_id)
    fixtures.set_clock(base["center_id"], "2026-05-08T00:00:00Z", wc_id)
    fixtures.record_assessment(base["patient_id"], wc_id, stage="STAGE_3",
                               length_cm=5, width_cm=3, tissue_type="GRANULATION")
    fixtures.set_clock(base["center_id"], "2026-05-15T00:00:00Z", wc_id)
    fixtures.record_assessment(base["patient_id"], wc_id, stage="STAGE_3",
                               length_cm=4, width_cm=3, tissue_type="GRANULATION")
    base["plan_id"] = plan["id"]
    return base


def test_outcome_report_actual_healing_pct(api):
    """PRD §3.4: "The actual healing percentage is the baseline area minus the
    latest area, divided by the baseline area, multiplied by 100, and rounded
    half up to two decimal places."
    baseline 20, latest 12 -> (20-12)/20*100 == 40.0.

    Design: Difficulty/dual_variant_calc/healing_trajectory_actual_vs_projected_diverge
    """
    base = _build_three_assessment_plan(api, "M1a")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    report = validate_success(api.outcome_report_treatment_plan(base["plan_id"], wc_headers), 201)
    assert report["actual_healing_pct"] == 40.0, \
        f"expected actual 40.0, got {report['actual_healing_pct']}"


def test_outcome_report_projected_diverges_from_actual(api):
    """PRD §3.4: "The projected healing percentage is a forward-looking four-week
    projection: first compute a weekly reduction rate as the previous area minus
    the latest area, divided by the number of days between the previous and
    latest assessments (a strictly positive span), multiplied by 7; then take
    that weekly rate, divide by the baseline area, multiply by 100, and multiply
    by 4, round half up to two decimal places, and cap the result at 100.0."
    prev 15, latest 12, 7 days -> weekly rate (15-12)/7*7 == 3; 3/20*100*4 == 60.0,
    distinct from actual 40.0.

    Design: Difficulty/dual_variant_calc/healing_trajectory_actual_vs_projected_diverge
    """
    base = _build_three_assessment_plan(api, "M1b")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    report = validate_success(api.outcome_report_treatment_plan(base["plan_id"], wc_headers), 201)
    assert report["projected_healing_pct"] == 60.0, \
        f"expected projected 60.0, got {report['projected_healing_pct']}"
    assert report["actual_healing_pct"] != report["projected_healing_pct"], \
        "actual and projected must diverge on the same report"


# =============================================================================
# hbo_coverage_cost — provisional vs finalized divergence (PRD §3.8)
# =============================================================================

def _plan_two_sessions_one_completed(api, mrn):
    """Plan ACTIVE+COVERED; two SCHEDULED sessions; sess1 completed, sess2 stays
    SCHEDULED. Returns (base, sess1_id, sess2_id)."""
    base = fixtures.setup_active_covered_plan_with_chamber(mrn=mrn)
    ht_id = base["ht_id"]
    sess1 = fixtures.schedule_hbo_session(
        base["plan_id"], base["chamber_id"], ht_id,
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z")
    sess2 = fixtures.schedule_hbo_session(
        base["plan_id"], base["chamber_id"], ht_id,
        window_start="2026-05-02T11:00:00Z", window_end="2026-05-02T12:00:00Z")
    fixtures.complete_hbo_session(sess1["id"], ht_id)
    return base, sess1["id"], sess2["id"]


def test_provisional_hbo_after_cancel_one_of_two(api):
    """PRD §3.8: "The provisional estimate counts the plan's sessions currently
    in SCHEDULED or COMPLETED status, takes the smaller of that count and the
    cap, and multiplies by the rate to yield provisional_hbo_covered_cents".
    After one of two sessions completes and the other is cancelled, one session
    remains COMPLETED: provisional == 1 * 45000 == 45000.

    Design: Difficulty/dual_variant_calc/hbo_coverage_provisional_vs_finalized_diverge
    """
    base, sess1_id, sess2_id = _plan_two_sessions_one_completed(api, "M2a")
    ht_id = base["ht_id"]
    fixtures.api_client.cancel_hbo_session(sess2_id, make_hyperbaric_tech_headers(ht_id))
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_hbo_covered_cents"] == 45000, \
        f"expected provisional 45000, got {plan['provisional_hbo_covered_cents']}"


def test_finalized_hbo_counts_only_completed(api):
    """PRD §3.8: "The finalized figure, computed at outcome reporting, counts
    only the plan's COMPLETED sessions, takes the smaller of that count and the
    cap, and multiplies by the rate to yield finalized_hbo_covered_cents."
    With exactly one COMPLETED session (the other cancelled before close),
    finalized == 1 * 45000 == 45000.

    Design: Difficulty/dual_variant_calc/hbo_coverage_provisional_vs_finalized_diverge
    """
    base, sess1_id, sess2_id = _plan_two_sessions_one_completed(api, "M2b")
    ht_id = base["ht_id"]
    fixtures.api_client.cancel_hbo_session(sess2_id, make_hyperbaric_tech_headers(ht_id))
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    report = validate_success(api.outcome_report_treatment_plan(base["plan_id"], wc_headers), 201)
    assert report["finalized_hbo_covered_cents"] == 45000, \
        f"expected finalized 45000, got {report['finalized_hbo_covered_cents']}"
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["finalized_hbo_covered_cents"] == 45000, \
        f"expected plan finalized 45000, got {plan['finalized_hbo_covered_cents']}"


# =============================================================================
# Corner: calculations section
# =============================================================================

def test_patient_latest_wound_area_reconciled_on_new_assessment(api):
    """PRD §3.2: "A patient carries a latest_wound_area_cm2 that starts at zero
    and always mirrors the area_cm2 of that patient's most recent wound
    assessment, ordered by assessed_at descending with ties broken by created_at
    descending".
    After a later 3x3=9 assessment, latest_wound_area_cm2 == 9.0 (not the
    earlier 2x2=4.0).

    Design: Corner/calculations/patient_latest_wound_area_reconciled_on_new_assessment
    """
    base = fixtures.setup_center_staff_patient(mrn="Mrec")
    wc_id = base["wc_id"]
    fixtures.set_clock(base["center_id"], "2026-05-01T00:00:00Z", wc_id)
    fixtures.record_assessment(base["patient_id"], wc_id, stage="STAGE_2",
                               length_cm=2, width_cm=2, tissue_type="GRANULATION")
    fixtures.set_clock(base["center_id"], "2026-05-08T00:00:00Z", wc_id)
    asm2 = validate_success(api.create_wound_assessment(
        factories.create_wound_assessment_payload(
            base["patient_id"], stage="STAGE_2", length_cm=3, width_cm=3,
            tissue_type="GRANULATION"),
        make_wound_clinician_headers(wc_id)), 201)
    assert asm2["area_cm2"] == 9.0
    patient = validate_success(api.get_patient(base["patient_id"], fixtures.INTAKE))
    assert patient["latest_wound_area_cm2"] == 9.0, \
        f"expected 9.0, got {patient['latest_wound_area_cm2']}"


def test_provisional_hbo_counts_scheduled_and_completed(api):
    """PRD §3.8: "The provisional estimate counts the plan's sessions currently
    in SCHEDULED or COMPLETED status, takes the smaller of that count and the
    cap, and multiplies by the rate to yield provisional_hbo_covered_cents".
    Two SCHEDULED sessions at per_session 45000 -> provisional == 90000.

    Design: Corner/calculations/hbo_provisional_counts_scheduled_and_completed
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mprov")
    ht_id = base["ht_id"]
    fixtures.schedule_hbo_session(
        base["plan_id"], base["chamber_id"], ht_id,
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z")
    fixtures.schedule_hbo_session(
        base["plan_id"], base["chamber_id"], ht_id,
        window_start="2026-05-02T11:00:00Z", window_end="2026-05-02T12:00:00Z")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_hbo_covered_cents"] == 90000, \
        f"expected 90000, got {plan['provisional_hbo_covered_cents']}"
