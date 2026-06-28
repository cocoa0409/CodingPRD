"""Pricing engine (estimate vs invoice), duration, and risk-score calculations."""
import pytest

from test_helpers import (
    api_client as api, get_success_data, validate_success, validate_paginated,
    TEST_USERS, make_technician_headers,
    create_active_pricing_config, create_home_with_systems, create_home_with_active_plan,
    create_crew, create_quoted_work_order, create_completed_work_order,
    create_in_progress_work_order, complete, quote, inspect,
    create_work_order, create_inspected_work_order,
    duct_line, sanitize_line, dryer_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================
def test_estimate_and_invoice_diverge_when_system_decommissioned_after_quote():
    """PRD §3.4: "Because the estimate is a snapshot, a system added to or
    decommissioned from the home after the quote does not change
    estimate_total_cents; the figure is frozen at quote time."
    PRD §3.8: "it uses the home's active_system_count read live at completion time,
    which may differ from the count at quote time"

    Design: Difficulty/dual_variant_calc/dual_variant_estimate_vs_invoice_diverge_on_system_change
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=2000)
    crew = create_crew(home_zone_code="Z1", certified_for_uv=True)
    lines = [duct_line(systems[0]["id"]), dryer_line()]
    wo, route = create_in_progress_work_order(
        home["id"], lines, crew["id"], scheduled_start_minute=540,
        addons=["UV"], inspect_overrides={"before_photo_count": 3, "dust_severity": 5},
        service_date="2026-04-10")
    estimate = wo["estimate_total_cents"]
    assert estimate == 36720, f"Expected estimate 36720 at n=3, got {estimate}"

    # Decommission one system so active_system_count drops to 2 before completion.
    get_success_data(api.decommission_system(home["id"], systems[2]["id"], PA))

    completed = complete(wo["id"], crew["id"],
                        [duct_line(systems[0]["id"]), dryer_line()],
                        after_photo_count=4, dust_severity=5, performed_addons=["UV"])
    invoice = completed["invoice_total_cents"]
    assert invoice == 32832, f"Expected invoice 32832 at n=2, got {invoice}"
    assert estimate != invoice, "estimate and invoice must diverge after the system change"


def test_invoice_independent_of_contamination_risk_referral():
    """PRD §3.8: "A repair referral is warranted exactly when the resulting score
    is at least forty."
    PRD §3.10: "severity_at_referral, a snapshot of the AFTER inspection's
    dust_severity at referral time."

    Design: Difficulty/dual_variant_calc/dual_variant_cost_vs_contamination_risk_different_domains
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=8, zone_code="Z1",
                                            square_footage=1800)
    crew = create_crew(home_zone_code="Z1")
    lines = [duct_line(systems[0]["id"])]
    wo, route = create_in_progress_work_order(
        home["id"], lines, crew["id"], scheduled_start_minute=600,
        inspect_overrides={"before_photo_count": 2, "dust_severity": 6},
        service_date="2026-04-11")
    completed = complete(wo["id"], crew["id"], [duct_line(systems[0]["id"])],
                        after_photo_count=3, dust_severity=4, recommend_hvac_repair=True)
    assert completed["invoice_total_cents"] == 19440, \
        f"Expected invoice 19440, got {completed['invoice_total_cents']}"

    referrals, _ = validate_paginated(api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    assert len(referrals) == 1, f"Expected exactly one referral, got {len(referrals)}"
    ref = referrals[0]
    assert ref["status"] == "PENDING"
    assert ref["severity_at_referral"] == 4, \
        f"severity_at_referral must snapshot AFTER dust_severity 4, got {ref['severity_at_referral']}"


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================
def test_duration_applies_big_home_factor_when_both_conditions_hold():
    """PRD §3.5: "the per-line component is multiplied by a factor of 1.25 and
    rounded half up before being added in. The final duration_minutes is the
    setup allowance plus the (possibly surcharged) per-line component plus the
    per-add-on component."

    Design: Difficulty/combinatorial_formula/combinatorial_duration_nonlinear_big_home_factor
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=6, zone_code="Z1",
                                            square_footage=3500)
    crew = create_crew(home_zone_code="Z1", certified_for_uv=True)
    lines = [duct_line(systems[0]["id"]), dryer_line()]
    wo = create_quoted_work_order(home["id"], lines, crew["id"], addons=["UV"],
                                 inspect_overrides={"before_photo_count": 2, "dust_severity": 5})
    assert wo["duration_minutes"] == 105, \
        f"Expected duration 105 (60*1.25=75 +20 +10), got {wo['duration_minutes']}"


def test_estimate_pins_evaluation_order_discount_then_plan_then_tax():
    """PRD §3.4: "The plan-member discount applies to that whole service subtotal,
    but only after the multi-system discount has already been applied — the
    evaluation order is fixed."
    PRD §2.7: "the multi-system discount is rounded, then the plan-member discount
    is rounded, then the tax is rounded, and only then are the rounded parts summed."

    Design: Difficulty/combinatorial_formula/combinatorial_estimate_pinned_eval_order_discount_then_plan_then_tax
    """
    create_active_pricing_config()
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=3,
                                                      register_count=6, zone_code="Z1",
                                                      square_footage=2200)
    crew = create_crew(home_zone_code="Z1")
    lines = [duct_line(systems[0]["id"]), duct_line(systems[1]["id"]),
             sanitize_line(systems[2]["id"]), dryer_line()]
    wo = create_quoted_work_order(home["id"], lines, crew["id"],
                                 addons=["SANITIZER", "COIL"],
                                 inspect_overrides={"before_photo_count": 2, "dust_severity": 3})
    assert wo["estimate_total_cents"] == 50949, \
        f"Expected estimate 50949 (round-per-step), got {wo['estimate_total_cents']}"


# ===========================================================================
# Difficulty: boundary_precision_check (multi-system discount threshold)
# ===========================================================================
def test_multi_system_discount_does_not_apply_at_one_system():
    """PRD §3.4: "when the home's active system count is at least two — the
    multi-system threshold is two systems — the duct subtotal is replaced by the
    duct subtotal multiplied by one minus multi_system_discount_pct, rounded half up."

    Design: Difficulty/boundary_precision_check/boundary_multi_system_discount_triggers_at_two_not_one
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    assert wo["estimate_total_cents"] == 12960, \
        f"n=1 must not discount: expected 12960, got {wo['estimate_total_cents']}"


def test_multi_system_discount_applies_at_two_systems():
    """PRD §3.4: "when the home's active system count is at least two — the
    multi-system threshold is two systems — the duct subtotal is replaced by the
    duct subtotal multiplied by one minus multi_system_discount_pct, rounded half up."

    Design: Difficulty/boundary_precision_check/boundary_multi_system_discount_triggers_at_two_not_one
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(2, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    assert wo["estimate_total_cents"] == 15552, \
        f"n=2 must discount the duct line: expected 15552, got {wo['estimate_total_cents']}"


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_single_system_estimate_no_discount():
    """PRD §3.4: "The duct subtotal is the number of DUCT lines multiplied by a
    per-line price, where that per-line price is duct_base_cents plus
    duct_per_system_cents times the number of active systems beyond the first"

    Design: Corner/calculations/calc_single_system_no_discount_correct_total
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_quoted_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    assert wo["estimate_total_cents"] == 12960, \
        f"Expected 12960 (12000 + 8% tax 960), got {wo['estimate_total_cents']}"


def test_no_referral_when_risk_below_threshold():
    """PRD §3.8: "A repair referral is warranted exactly when the resulting score
    is at least forty."

    Design: Corner/calculations/calc_risk_below_threshold_no_referral
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=4, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    lines = [duct_line(systems[0]["id"])]
    wo, route = create_in_progress_work_order(
        home["id"], lines, crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 3},
        service_date="2026-04-25")
    # AFTER severity 2, register_sum 12, n=3 -> 16 + round(4)*2 = 24 < 40.
    complete(wo["id"], crew["id"], [duct_line(systems[0]["id"])],
             after_photo_count=2, dust_severity=2, recommend_hvac_repair=False)
    referrals, meta = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    assert meta["total_count"] == 0, \
        f"No referral expected when score 24 < 40, got total_count {meta['total_count']}"


def test_duration_no_big_home_factor_below_sqft_threshold():
    """PRD §3.5: "a non-linear "big-home" surcharge then applies, but only to the
    per-line component and only when two conditions hold together: the home's
    active system count is at least two and the home's square_footage is at least
    three thousand."

    Design: Corner/calculations/calc_duration_no_big_home_factor_below_sqft
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(3, register_count=5, zone_code="Z1",
                                            square_footage=2000)
    crew = create_crew(home_zone_code="Z1")
    lines = [duct_line(systems[0]["id"]), dryer_line()]
    wo = create_quoted_work_order(home["id"], lines, crew["id"],
                                 inspect_overrides={"before_photo_count": 1, "dust_severity": 3})
    # per_line = 35 + 25 = 60 (no factor since sqft 2000 < 3000); 20 + 60 = 80.
    assert wo["duration_minutes"] == 80, \
        f"Expected duration 80 (no big-home factor), got {wo['duration_minutes']}"


# ===========================================================================
# Corner: consistency_model
# ===========================================================================
def test_quote_response_carries_estimate_immediately():
    """PRD §2.5: "The platform's consistency model is immediate: every cascade
    lands within the same operation that triggered it, so a read taken after the
    operation observes the fully reconciled state."
    PRD §3.3: "Quoting then computes the work order's estimate_total_cents and its
    duration_minutes"

    Design: Corner/consistency_model/consistency_immediate_estimate_visible_in_quote_response
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_inspected_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                    inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    resp = api.quote_work_order(wo["id"], make_technician_headers(crew["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["estimate_total_cents"] == 12960, \
        f"Quote response must carry estimate 12960, got {data['estimate_total_cents']}"
    assert data["status"] == "QUOTED"
