"""Mid-cycle change-plan proration and dual-variant patient monitoring risk."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_patient, create_membership_plan, create_membership, set_clock,
    create_clinician, create_reviewed_panel,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_change_plan_per_line_rounding_net_charge(api):
    """PRD §3.2: "Compute the old-plan credit line as the old plan's `monthly_fee_cents`
    multiplied by `days_remaining`, divided by the old plan's `cycle_days`, rounded half
    up to a whole cent. Compute the new-plan charge line as the new plan's
    `monthly_fee_cents` multiplied by `days_remaining`, divided by the new plan's
    `cycle_days`, rounded half up to a whole cent."
    PRD §3.2: "The net proration charge is the new-plan charge line minus the old-plan
    credit line; this value is stored in `last_change_charge_cents`".

    Design: Difficulty/combinatorial_formula/change_plan_per_line_rounding_mode_b
    """
    patient = create_patient()
    old_plan = create_membership_plan(tier="PLUS", monthly_fee_cents=9999, cycle_days=30)
    new_plan = create_membership_plan(
        tier="ELITE", monthly_fee_cents=14999, cycle_days=28,
        included_refills_per_cycle=8, included_lab_draw_credits=8,
        refill_discount_pct=0.35, titration_visit_fee_cents=3000,
    )
    membership = create_membership(patient["id"], old_plan["id"], activate=True)
    set_clock("2026-05-18T00:00:00Z")  # anchor 2026-05-01 + 30 -> 2026-05-31; days_remaining = 13
    data = validate_success(api.change_plan(membership["id"], {"new_plan_id": new_plan["id"]}, ADMIN), 200)
    # old_credit = round(9999*13/30)=4333; new_charge = round(14999*13/28)=6964; net = 2631
    assert data["last_change_charge_cents"] == 2631


def test_change_plan_updates_plan_id(api):
    """PRD §3.2: "this value is stored in `last_change_charge_cents`, and the
    membership's `plan_id` is updated to `new_plan_id`."

    Design: Difficulty/combinatorial_formula/change_plan_per_line_rounding_mode_b
    """
    patient = create_patient()
    old_plan = create_membership_plan(tier="PLUS", monthly_fee_cents=9999, cycle_days=30)
    new_plan = create_membership_plan(tier="ELITE", monthly_fee_cents=14999, cycle_days=28)
    membership = create_membership(patient["id"], old_plan["id"], activate=True)
    set_clock("2026-05-18T00:00:00Z")
    data = validate_success(api.change_plan(membership["id"], {"new_plan_id": new_plan["id"]}, ADMIN), 200)
    assert data["plan_id"] == new_plan["id"]


def _setup_two_risk_panels():
    clinician = create_clinician()
    patient = create_patient()
    # Older panel: hct 52 (=> 8*2=16), psa 3.5 (=> 15*1=15), t 280 (< 300 => 25) = 56
    create_reviewed_panel(
        patient["id"], clinician["id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 280, "psa_ng_ml": 3.5, "hematocrit_pct": 52.0, "drawn_at": "2026-04-10T09:00:00Z"},
    )
    # Latest panel: hct 55 (=> 8*5=40), psa 4.2 (=> 15*2=30), t 350 (>= 300 => 0) = 70
    create_reviewed_panel(
        patient["id"], clinician["id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 350, "psa_ng_ml": 4.2, "hematocrit_pct": 55.0, "drawn_at": "2026-04-25T09:00:00Z"},
    )
    return patient


def test_provisional_risk_uses_latest_panel(api):
    """PRD §3.8: "The `provisional_risk_score` is the per-panel score of the single most
    recent in-window panel, chosen by latest `drawn_at`, breaking ties by latest
    `created_at`."

    Design: Difficulty/dual_variant_calc/patient_risk_provisional_vs_comprehensive
    """
    patient = _setup_two_risk_panels()
    data = validate_success(api.get_monitoring_summary(patient["id"], ADMIN), 200)
    assert data["provisional_risk_score"] == 70


def test_comprehensive_risk_averages_window(api):
    """PRD §3.8: "The `comprehensive_risk_score` is the mean of the per-panel scores
    across all in-window panels, rounded half up to a whole integer; when there are no
    in-window panels, both scores are 0."
    PRD §3.8: "`reviewed_panels_in_window` is the count of those panels."

    Design: Difficulty/dual_variant_calc/patient_risk_provisional_vs_comprehensive
    """
    patient = _setup_two_risk_panels()
    data = validate_success(api.get_monitoring_summary(patient["id"], ADMIN), 200)
    # mean(56, 70) = 63.0 -> 63
    assert data["comprehensive_risk_score"] == 63
    assert data["reviewed_panels_in_window"] == 2
