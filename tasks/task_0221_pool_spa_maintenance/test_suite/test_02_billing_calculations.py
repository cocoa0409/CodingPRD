"""Per-visit billing and repair-total calculation tests (PRD §3.5, §3.9)."""
from test_helpers import (
    validate_success,
    setup_open_pool_dispatched_visit, setup_work_order_awaiting_approval,
    complete_payload, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]


def test_green_initial_visit_bills_base_plus_tier2_surcharge(api):
    """PRD §3.5: "A green-pool initial visit — one that was `SCHEDULED` and
    completed with `green_pool` true — instead adds a chemical surcharge tiered by
    the pool's `volume_gallons`: 12000 cents when the volume is at most 15000
    gallons, 18000 cents when the volume is at most 30000 gallons (and above 15000),
    and 26000 cents when the volume exceeds 30000 gallons."
    PRD §3.5: "The gross figure is the base rate plus whichever surcharge applies."

    Design: Difficulty/dual_variant_calc/visit_bill_provisional_quote_vs_final_on_service_visit
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="ONE_TIME",
                                           frequency="NONE", per_visit_rate_cents=8000)
    resp = api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT)
    data = validate_success(resp)
    # base 8000 + tier2 (15000<20000<=30000) 18000 = 26000
    assert data["billed_amount_cents"] == 26000, \
        f"expected 26000, got {data['billed_amount_cents']}"


def test_green_initial_visit_bill_exceeds_plan_base_rate(api):
    """PRD §3.5: "The gross figure is the base rate plus whichever surcharge applies."
    PRD §3.5: "Surcharges are always billed, even when the base is prepaid."

    The final bill (base + green surcharge) diverges from the bare per-visit rate.

    Design: Difficulty/dual_variant_calc/visit_bill_provisional_quote_vs_final_on_service_visit
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="ONE_TIME",
                                           frequency="NONE", per_visit_rate_cents=8000)
    resp = api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT)
    data = validate_success(resp)
    plan = validate_success(api.get_service_plan(ctx["plan"]["id"], TEST_USERS["account_manager_headers"]))
    assert data["billed_amount_cents"] == 26000
    assert data["billed_amount_cents"] != plan["per_visit_rate_cents"]


def test_prepaid_recurring_base_covered_only_surcharge_billed(api):
    """PRD §3.5: "if the plan is `RECURRING` and its `visits_remaining` was greater
    than 0 immediately before this completion, the base portion is treated as
    already paid and the billed amount is only the surcharge component (recovery
    and/or green surcharge); otherwise the billed amount is the full gross.
    Surcharges are always billed, even when the base is prepaid."

    Design: Corner/calculations/prepaid_recurring_base_covered_surcharge_billed
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=12000, plan_type="RECURRING",
                                           frequency="WEEKLY", per_visit_rate_cents=6000,
                                           prepaid_visit_count=4)
    resp = api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT)
    data = validate_success(resp)
    # prepaid 4 (>0) covers base 6000; tier1 green surcharge (vol 12000 <= 15000) = 12000 billed
    assert data["billed_amount_cents"] == 12000, \
        f"expected 12000, got {data['billed_amount_cents']}"


def test_non_green_recurring_visit_bills_full_base(api):
    """PRD §3.5: "A visit that is neither a recovery visit nor a green-pool initial
    visit adds no surcharge. The gross figure is the base rate plus whichever
    surcharge applies." PRD §3.5: "otherwise the billed amount is the full gross."

    A RECURRING plan with prepaid_visit_count 0 has visits_remaining 0 before the
    completion, so the full base is billed.

    Design: Difficulty/non_linear_state_machine/service_visit_branching_complete_vs_skip
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="RECURRING",
                                           frequency="WEEKLY", per_visit_rate_cents=6000)
    resp = api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=False), FT)
    data = validate_success(resp)
    assert data["status"] == "COMPLETED"
    assert data["billed_amount_cents"] == 6000, \
        f"expected 6000, got {data['billed_amount_cents']}"


def test_repair_total_major_pinned_evaluation_order(api):
    """PRD §3.9: "First, labor is billed in whole hours: the estimated
    `labor_minutes` is divided by 60 and rounded up to the next whole hour, then
    multiplied by a labor rate of 9000 cents per hour. Second, a severity multiplier
    is applied to the labor figure alone — 1.0 for `MINOR`, 1.15 for `MAJOR`, and
    1.35 for `CRITICAL`. Third, the `quoted_parts_cents` is added to the
    multiplier-adjusted labor; parts are neither multiplied by severity nor taxed
    separately. Fourth, the running pre-tax total is multiplied by one plus a tax
    rate of 0.07, and that taxed total is rounded once at the very end using
    round-half-up to yield the integer-cent `repair_total_cents`."

    Design: Difficulty/combinatorial_formula/repair_total_pinned_evaluation_order
    """
    ctx = setup_work_order_awaiting_approval(severity="MAJOR", component="PUMP",
                                             quoted_parts_cents=5000, labor_minutes=90)
    resp = api.resolve_work_order(ctx["work_order"]["id"], ctx["customer_headers"])
    data = validate_success(resp)
    # ceil(90/60)=2 hr*9000=18000 *1.15=20700 +5000=25700 *1.07=27499.0 -> 27499
    assert data["repair_total_cents"] == 27499, \
        f"expected 27499, got {data['repair_total_cents']}"


def test_repair_total_labor_ceil_to_whole_hour(api):
    """PRD §3.9: "First, labor is billed in whole hours: the estimated
    `labor_minutes` is divided by 60 and rounded up to the next whole hour, then
    multiplied by a labor rate of 9000 cents per hour."
    PRD §3.9: "a severity multiplier is applied to the labor figure alone — 1.0 for
    `MINOR`".
    PRD §3.9: "the running pre-tax total is multiplied by one plus a tax rate of
    0.07, and that taxed total is rounded once at the very end using round-half-up".

    61 labor minutes ceils up to 2 whole hours (not 1), exercising the ceil rule.

    Design: Difficulty/combinatorial_formula/repair_total_pinned_evaluation_order
    """
    ctx = setup_work_order_awaiting_approval(severity="MINOR", component="LINER",
                                             quoted_parts_cents=3000, labor_minutes=61)
    resp = api.resolve_work_order(ctx["work_order"]["id"], ctx["customer_headers"])
    data = validate_success(resp)
    # ceil(61/60)=2 hr*9000=18000 *1.0=18000 +3000=21000 *1.07=22470.0 -> 22470
    assert data["repair_total_cents"] == 22470, \
        f"expected 22470, got {data['repair_total_cents']}"


def test_repair_total_critical_severity_and_tax_round_half_up(api):
    """PRD §3.9: "a severity multiplier is applied to the labor figure alone — 1.0
    for `MINOR`, 1.15 for `MAJOR`, and 1.35 for `CRITICAL`."
    PRD §3.9: "the running pre-tax total is multiplied by one plus a tax rate of
    0.07, and that taxed total is rounded once at the very end using round-half-up
    to yield the integer-cent `repair_total_cents`."

    Design: Corner/calculations/repair_critical_severity_multiplier_and_tax_round
    """
    ctx = setup_work_order_awaiting_approval(severity="CRITICAL", component="PUMP",
                                             quoted_parts_cents=30000, labor_minutes=60)
    resp = api.resolve_work_order(ctx["work_order"]["id"], ctx["customer_headers"])
    data = validate_success(resp)
    # ceil(60/60)=1*9000=9000 *1.35=12150 +30000=42150 *1.07=45100.5 -> round-half-up 45101
    assert data["repair_total_cents"] == 45101, \
        f"expected 45101, got {data['repair_total_cents']}"
