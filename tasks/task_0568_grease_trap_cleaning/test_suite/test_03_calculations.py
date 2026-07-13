"""Calculations: dual-variant valuations, tiered fees, tax rounding, FOG boundary (difficulty),
plus single-tier fee and immediate lifetime accumulation (corner)."""
from test_helpers import (
    validate_success,
    TEST_USERS, make_technician_headers, get_success_data,
)
from test_helpers.fixtures import (
    set_clock, new_customer, new_site, new_equipment, new_technician, new_work_order,
    new_active_contract, new_draft_invoice, dispatch_work_order, start_work_order,
    file_manifest, setup_inprogress_grease_work_order,
)
from test_helpers.api_client import api_client
from test_helpers.constants import DEFAULT_CLOCK

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─────────────── Difficulty: provisional vs final invoice divergence ───────────────
def _setup_two_scheduled_grease_wos_with_draft_invoice():
    set_clock(DEFAULT_CLOCK)
    cust = new_customer(business_name="Divergence Diner", credit_limit_cents=1000000)
    site = new_site(cust["id"])
    eq1 = new_equipment(site["id"], capacity_gallons=100, nominal_frequency_days=30)
    eq2 = new_equipment(site["id"], capacity_gallons=100, nominal_frequency_days=30)
    contract = new_active_contract(cust["id"], base_rate_cents=0, tax_rate_bps=0)
    tech = new_technician("BASIC")
    wo1 = new_work_order(site["id"], eq1["id"], planned_start="2026-05-10T08:00:00Z",
                         planned_end="2026-05-10T10:00:00Z", contract_id=contract["id"])
    wo2 = new_work_order(site["id"], eq2["id"], planned_start="2026-05-11T08:00:00Z",
                         planned_end="2026-05-11T10:00:00Z", contract_id=contract["id"])
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    return {"cust": cust, "eq1": eq1, "eq2": eq2, "contract": contract, "tech": tech,
            "wo1": wo1, "wo2": wo2, "inv": inv}


def test_provisional_total_counts_scheduled_work_orders(api):
    """PRD §3.7: "The provisional valuation, stored in `provisional_total_cents` at draft
    creation, is forward-looking: it counts work orders in the period whose status is
    `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED`."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverges
    """
    ctx = _setup_two_scheduled_grease_wos_with_draft_invoice()
    assert ctx["inv"]["provisional_total_cents"] == 25000, \
        "provisional must count both SCHEDULED grease orders (2 x 12500)"


def test_final_total_counts_only_completed_work_orders(api):
    """PRD §3.7: "The final valuation, frozen into `subtotal_cents`, `tax_cents`, and
    `total_amount_cents` at issue, is chronological: it counts only work orders whose status
    is `COMPLETED` and whose `completed_at` falls at or after `period_start` and before `period_end`."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverges
    """
    ctx = _setup_two_scheduled_grease_wos_with_draft_invoice()
    # Complete WO1; cancel WO2.
    dispatch_work_order(ctx["wo1"]["id"], ctx["tech"]["id"])
    start_work_order(ctx["wo1"]["id"], ctx["tech"]["id"])
    file_manifest(ctx["wo1"]["id"], ctx["tech"]["id"], disposal_facility_permit="FAC-9",
                  volume_gallons=100)
    get_success_data(api_client.complete_work_order(
        ctx["wo1"]["id"], {"actual_hours": 2}, make_technician_headers(ctx["tech"]["id"])))
    get_success_data(api_client.transition_work_order(
        ctx["wo2"]["id"], {"to_status": "CANCELLED"}, DISPATCHER))
    issued = validate_success(api.issue_invoice(ctx["inv"]["id"], BILLING), 200)
    assert issued["total_amount_cents"] == 12500, \
        "final must count only the one COMPLETED order (12500)"


# ─────────────── Difficulty: site compliance as-of vs projected ───────────────
def _setup_site_with_equipment_due_in_20_days():
    set_clock(DEFAULT_CLOCK)
    cust = new_customer(business_name="Horizon Grill")
    site = new_site(cust["id"])
    eq = new_equipment(site["id"], nominal_frequency_days=20)
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"], planned_start="2026-05-01T08:00:00Z",
                        planned_end="2026-05-01T10:00:00Z")
    dispatch_work_order(wo["id"], tech["id"])
    start_work_order(wo["id"], tech["id"])
    file_manifest(wo["id"], tech["id"], disposal_facility_permit="FAC-1", volume_gallons=50)
    get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_hours": 1}, make_technician_headers(tech["id"])))
    return site


def test_as_of_compliance_uses_7_day_horizon(api):
    """PRD §3.2: "The `compliance_status` uses a 7-day due-soon horizon (the near-term,
    as-of view), while `projected_compliance_status` uses a 30-day horizon (the forward-looking
    view) — so a piece of equipment due in, say, 20 days grades the site `AT_RISK` under the
    projected view but `COMPLIANT` under the as-of view."

    Design: Difficulty/dual_variant_calc/site_compliance_as_of_vs_projected_diverges
    """
    site = _setup_site_with_equipment_due_in_20_days()
    fresh = validate_success(api.get_site(site["id"], COMPLIANCE), 200)
    assert fresh["compliance_status"] == "COMPLIANT", \
        "equipment due in 20 days is COMPLIANT under the 7-day as-of horizon"


def test_projected_compliance_uses_30_day_horizon(api):
    """PRD §3.2: "The `compliance_status` uses a 7-day due-soon horizon (the near-term,
    as-of view), while `projected_compliance_status` uses a 30-day horizon (the forward-looking
    view) — so a piece of equipment due in, say, 20 days grades the site `AT_RISK` under the
    projected view but `COMPLIANT` under the as-of view."

    Design: Difficulty/dual_variant_calc/site_compliance_as_of_vs_projected_diverges
    """
    site = _setup_site_with_equipment_due_in_20_days()
    fresh = validate_success(api.get_site(site["id"], COMPLIANCE), 200)
    assert fresh["projected_compliance_status"] == "AT_RISK", \
        "equipment due in 20 days is AT_RISK under the 30-day projected horizon"


# ─────────────── Difficulty: tiered disposal fee (3 interacting inputs) ───────────────
def test_disposal_fee_full_tiers_with_fog_and_hazmat(api):
    """PRD §3.4: "For example, 2000 gallons at a 25.0 percent reading from a hazmat-certified
    facility yields a gallons cost of 500×40 + 1000×35 + 500×30 = 70000, a surcharge of 20
    percent of 70000 = 14000, and a hazmat fee of 5000, for a total of 89000 cents."

    Design: Difficulty/combinatorial_formula/pump_out_disposal_fee_tiered_mode_a
    """
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 3000,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.create_manifest(
        {"work_order_id": ctx["wo_id"], "disposal_facility_name": "Acme",
         "disposal_facility_permit": "FAC-2", "hazmat_certified": True,
         "volume_gallons": 2000, "fog_percentage": 25.0},
        ctx["tech_headers"])
    man = validate_success(res, 201)
    assert man["disposal_fee_cents"] == 89000, "70000 gallons + 14000 fog + 5000 hazmat"


def test_disposal_fee_at_fog_threshold_flags_non_compliant(api):
    """PRD §3.4: "it is `COMPLIANT` when `fog_percentage` is strictly below 25.0 and
    `NON_COMPLIANT` when `fog_percentage` is 25.0 or greater — a reading of 24.99 is
    compliant, 25.00 is a breach."

    Design: Difficulty/combinatorial_formula/pump_out_disposal_fee_tiered_mode_a
    """
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 3000,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.create_manifest(
        {"work_order_id": ctx["wo_id"], "disposal_facility_name": "Acme",
         "disposal_facility_permit": "FAC-2", "hazmat_certified": True,
         "volume_gallons": 2000, "fog_percentage": 25.0},
        ctx["tech_headers"])
    man = validate_success(res, 201)
    assert man["compliance_flag"] == "NON_COMPLIANT", "fog 25.0 breaches the 25% rule"


# ─────────────── Difficulty: invoice tax rounded per line then summed ───────────────
def _setup_completed_grease_invoice_with_tax():
    set_clock(DEFAULT_CLOCK)
    cust = new_customer(business_name="Round Bistro", credit_limit_cents=1000000)
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    contract = new_active_contract(cust["id"], base_rate_cents=12500, tax_rate_bps=825)
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"], contract_id=contract["id"])
    dispatch_work_order(wo["id"], tech["id"])
    start_work_order(wo["id"], tech["id"])
    file_manifest(wo["id"], tech["id"], disposal_facility_permit="FAC-3", volume_gallons=50)
    get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_hours": 2}, make_technician_headers(tech["id"])))
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    return inv


def test_tax_rounds_each_line_then_sums(api):
    """PRD §3.7: "two work-order lines of 12500 each at a `tax_rate_bps` of 825 produce a
    per-line tax of round-half-up(1031.25) = 1031 each, so `tax_cents` is 2062, `subtotal_cents`
    is 25000, and `total_amount_cents` is 27062 — whereas summing before rounding would have
    yielded 2063."

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_mode_b
    """
    inv = _setup_completed_grease_invoice_with_tax()
    issued = validate_success(api.issue_invoice(inv["id"], BILLING), 200)
    assert issued["tax_cents"] == 2062, "per-line rounding yields 1031 + 1031 = 2062, not 2063"


def test_subtotal_and_total_over_two_lines(api):
    """PRD §3.7: "two work-order lines of 12500 each at a `tax_rate_bps` of 825 produce a
    per-line tax of round-half-up(1031.25) = 1031 each, so `tax_cents` is 2062, `subtotal_cents`
    is 25000, and `total_amount_cents` is 27062 — whereas summing before rounding would have
    yielded 2063."

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_mode_b
    """
    inv = _setup_completed_grease_invoice_with_tax()
    issued = validate_success(api.issue_invoice(inv["id"], BILLING), 200)
    assert issued["subtotal_cents"] == 25000, "base-rate line 12500 + work-order line 12500"
    assert issued["total_amount_cents"] == 27062, "subtotal 25000 + tax 2062"


# ─────────────── Difficulty: FOG 25% inclusive boundary ───────────────
def test_fog_below_threshold_is_compliant(api):
    """PRD §3.4: "it is `COMPLIANT` when `fog_percentage` is strictly below 25.0 and
    `NON_COMPLIANT` when `fog_percentage` is 25.0 or greater — a reading of 24.99 is
    compliant, 25.00 is a breach."

    Design: Difficulty/boundary_precision_check/fog_25_percent_inclusive_boundary
    """
    ctx = setup_inprogress_grease_work_order(
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    man = file_manifest(ctx["wo_id"], ctx["tech_id"], disposal_facility_permit="FAC-5",
                        volume_gallons=50, fog_percentage=24.99)
    assert man["compliance_flag"] == "COMPLIANT", "fog 24.99 is below the 25.0 breach"


def test_fog_at_threshold_is_non_compliant(api):
    """PRD §3.4: "it is `COMPLIANT` when `fog_percentage` is strictly below 25.0 and
    `NON_COMPLIANT` when `fog_percentage` is 25.0 or greater — a reading of 24.99 is
    compliant, 25.00 is a breach."

    Design: Difficulty/boundary_precision_check/fog_25_percent_inclusive_boundary
    """
    ctx = setup_inprogress_grease_work_order(
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    man = file_manifest(ctx["wo_id"], ctx["tech_id"], disposal_facility_permit="FAC-5",
                        volume_gallons=50, fog_percentage=25.0)
    assert man["compliance_flag"] == "NON_COMPLIANT", "fog 25.0 is an inclusive breach"


# ─────────────── Corner: single-tier disposal fee ───────────────
def test_disposal_fee_single_tier(api):
    """PRD §3.4: "The gallons cost charges the first 500 gallons at 40 cents per gallon,
    each gallon above 500 and up to 1500 at 35 cents per gallon, and each gallon above 1500
    at 30 cents per gallon."

    Design: Corner/calculations/disposal_fee_single_tier_correct
    """
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 500,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.create_manifest(
        {"work_order_id": ctx["wo_id"], "disposal_facility_name": "Acme",
         "disposal_facility_permit": "FAC-7", "hazmat_certified": False,
         "volume_gallons": 300, "fog_percentage": 5.0},
        ctx["tech_headers"])
    man = validate_success(res, 201)
    assert man["disposal_fee_cents"] == 12000, "300 gallons entirely in tier 1 at 40 = 12000"
    assert man["compliance_flag"] == "COMPLIANT", "fog 5 is compliant"


# ─────────────── Corner: immediate lifetime accumulation ───────────────
def test_manifest_immediately_updates_equipment_lifetime(api):
    """PRD §3.4: "On acceptance the server mints a `manifest_number`, sets `status` to
    `RECORDED`, adds `volume_gallons` to the equipment's `lifetime_pumped_gallons`, and
    re-grades the owning site's compliance."

    Design: Corner/consistency_model/manifest_create_immediately_updates_equipment_lifetime
    """
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 1000,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    file_manifest(ctx["wo_id"], ctx["tech_id"], disposal_facility_permit="FAC-10",
                  volume_gallons=250)
    fresh = validate_success(api.get_equipment(ctx["eq_id"], DISPATCHER), 200)
    assert fresh["lifetime_pumped_gallons"] == 250, "manifest volume is immediately visible"
