"""Work-order cost: estimate vs final divergence, tiered overage + emergency surcharge,
round-per-line invoice totals, and the gallon boundary.

Translates queue A `dual_variant_calc` (work-order variant), `combinatorial_formula`,
`boundary_precision_check` (gallon instance), and queue B `calculations` instances that
are not owned by an excluded stub.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, make_field_tech_headers,
    create_account, create_site, create_technician, create_route,
    create_service_plan, create_started_work_order, get_work_order,
    create_repair_line_payload, create_work_order_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Difficulty: dual_variant_calc (work-order cost) ───

def test_work_order_cost_estimate_differs_from_final(api):
    """PRD §3.5: "The estimate variant runs at scheduling: its gallons are the work order's
    estimated_gallons ... and it writes estimated_cost_cents. The final variant runs at
    completion: its gallons are the measured_gallons the field tech supplies, and it writes
    final_cost_cents."
    PRD §3.5: "Because the final run uses actual measured volume, the overage tier can land
    differently than the estimate did, so the two figures may legitimately diverge."

    Design: Difficulty/dual_variant_calc/work_order_cost_estimate_vs_final_diverge
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-10")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-10", 540,
        work_type="PUMPING", estimated_gallons=800,
    )
    assert wo["estimated_cost_cents"] == 29000
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1500}, make_field_tech_headers(tech["id"]))
    )
    assert completed["final_cost_cents"] == 54000
    assert completed["estimated_cost_cents"] == 29000


def test_work_order_cost_estimate_final_values_exact(api):
    """PRD §3.5: "take the gallons for the run, charge the lesser of that figure and 1000
    gallons at 25 cents each, charge any gallons above 1000 at 40 cents each, and add the
    9000-cent trip fee to that pumping subtotal."

    Design: Difficulty/dual_variant_calc/work_order_cost_estimate_vs_final_diverge
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-10")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-10", 540,
        work_type="PUMPING", estimated_gallons=800,
    )
    # estimate 800 gal -> 9000 + 800*25 = 29000
    assert wo["estimated_cost_cents"] == 29000
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1500}, make_field_tech_headers(tech["id"]))
    )
    # final 1500 gal -> 9000 + 1000*25 + 500*40 = 54000
    assert completed["final_cost_cents"] == 54000
    assert completed["final_cost_cents"] != completed["estimated_cost_cents"]


# ─── Difficulty: combinatorial_formula ─────────────────

def test_emergency_surcharge_applied_to_tiered_overage(api):
    """PRD §3.5: "If the emergency surcharge applies to the work order, increase the
    running total by an additional fifty percent of itself — that is, compute fifty percent
    of the current total (5000 basis points), round that addition half up to whole cents,
    and add it on."
    PRD §3.3: "emergency_surcharge_applies is set true exactly when work_type is EMERGENCY".

    Design: Difficulty/combinatorial_formula/pumping_tiered_overage_with_emergency_surcharge
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-11")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-11", 600,
        work_type="EMERGENCY", estimated_gallons=0,
    )
    assert wo["emergency_surcharge_applies"] is True
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1200}, make_field_tech_headers(tech["id"]))
    )
    # 9000 + 1000*25 + 200*40 = 42000; +50% = 63000
    assert completed["final_cost_cents"] == 63000


def test_emergency_surcharge_flag_drives_final_cost(api):
    """PRD §3.5: "The emergency surcharge flag is false for PUMPING and true for EMERGENCY."
    PRD §3.5: "compute fifty percent of the current total (5000 basis points), round that
    addition half up to whole cents, and add it on."

    Design: Difficulty/combinatorial_formula/pumping_tiered_overage_with_emergency_surcharge
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-11")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-11", 600,
        work_type="EMERGENCY", estimated_gallons=0,
    )
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1200}, make_field_tech_headers(tech["id"]))
    )
    assert completed["emergency_surcharge_applies"] is True
    assert completed["final_cost_cents"] == 63000


def test_repair_invoice_round_per_line_then_sum(api):
    """PRD §3.6: "each repair line is rounded to whole cents first, and only then are the
    already-rounded line totals summed — never sum-then-round."
    PRD §3.6: "The work order's invoice_total_cents is its final_cost_cents plus the parts
    total".

    Design: Difficulty/combinatorial_formula/repair_invoice_round_per_line_then_sum
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-12")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-12", 540, work_type="REPAIR"
    )
    ft = make_field_tech_headers(tech["id"])
    get_success_data(api.create_repair_line(
        create_repair_line_payload(wo["id"], part_name="Gasket", quantity=1,
                                   unit_price_cents=101, tax_rate_bps=825), ft))
    get_success_data(api.create_repair_line(
        create_repair_line_payload(wo["id"], part_name="Clamp", quantity=1,
                                   unit_price_cents=101, tax_rate_bps=825), ft))
    completed = get_success_data(api.complete_work_order(wo["id"], {}, ft))
    # REPAIR final cost = trip fee only = 9000; each line round(101*1.0825)=109; sum=218.
    assert completed["final_cost_cents"] == 9000
    assert completed["invoice_total_cents"] == 9218


def test_repair_line_total_rounded_half_up(api):
    """PRD §3.6: "Each line's line_total_cents is computed as the quantity times the unit
    price, scaled up by the tax rate (one plus the basis-point rate divided by ten
    thousand), with that single result rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/repair_invoice_round_per_line_then_sum
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-12")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-12", 540, work_type="REPAIR"
    )
    ft = make_field_tech_headers(tech["id"])
    line = get_success_data(api.create_repair_line(
        create_repair_line_payload(wo["id"], part_name="Gasket", quantity=1,
                                   unit_price_cents=101, tax_rate_bps=825), ft))
    # round_half_up(101 * 1.0825) = round_half_up(109.3325) = 109
    assert line["line_total_cents"] == 109


# ─── Difficulty: boundary_precision_check (gallon) ─────

def test_overage_boundary_exactly_at_included_gallons(api):
    """PRD §3.5: "The first 1000 gallons (the base-included volume) are priced at 25 cents
    per gallon, and every gallon beyond 1000 is priced at 40 cents per gallon."

    Design: Difficulty/boundary_precision_check/overage_boundary_exactly_at_included_gallons
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-17")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-17", 540,
        work_type="PUMPING", estimated_gallons=1000,
    )
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1000}, make_field_tech_headers(tech["id"]))
    )
    # exactly 1000 gal -> no overage -> 9000 + 1000*25 = 34000
    assert completed["final_cost_cents"] == 34000


def test_overage_boundary_one_gallon_over_adds_tier2(api):
    """PRD §3.5: "every gallon beyond 1000 is priced at 40 cents per gallon."
    PRD §3.5: "charge the lesser of that figure and 1000 gallons at 25 cents each, charge
    any gallons above 1000 at 40 cents each".

    Design: Difficulty/boundary_precision_check/overage_boundary_exactly_at_included_gallons
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-17")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-06-17", 540,
        work_type="PUMPING", estimated_gallons=1001,
    )
    completed = get_success_data(
        api.complete_work_order(wo["id"], {"measured_gallons": 1001}, make_field_tech_headers(tech["id"]))
    )
    # 1001 gal -> 9000 + 1000*25 + 1*40 = 34040
    assert completed["final_cost_cents"] == 34040


# ─── Corner: calculations (estimate defaults from plan) ─

def test_schedule_pumping_estimate_defaults_gallons_from_plan(api):
    """PRD §3.4: "defaults estimated_gallons from the site's ACTIVE service plan's
    estimated_gallons when the field was omitted and the work type is PUMPING, computes
    estimated_cost_cents".

    Design: Corner/calculations/schedule_pumping_estimate_defaults_gallons_from_plan
    """
    account = create_account()
    site = create_site(account["id"])
    create_service_plan(site["id"], site["version"], frequency_months=36, estimated_gallons=800)
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-06")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-06", 540), DISPATCHER
    ))
    scheduled = validate_success(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER), 200)
    assert scheduled["estimated_gallons"] == 800
    assert scheduled["estimated_cost_cents"] == 29000


def test_complete_pumping_without_measured_gallons_returns_measurement_required(api):
    """PRD §3.5: "for PUMPING and EMERGENCY work, the field tech must supply
    measured_gallons, and it must be present and at least zero; a completion of those types
    without measured_gallons is rejected with ERR_MEASUREMENT_REQUIRED."

    Design: Corner/calculations/complete_pumping_without_measured_gallons_returns_measurement_required
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-08")
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-07-08", 540,
        work_type="PUMPING", estimated_gallons=500,
    )
    res = api.complete_work_order(wo["id"], {}, make_field_tech_headers(tech["id"]))
    validate_error(res, "ERR_MEASUREMENT_REQUIRED", expected_status=422)
