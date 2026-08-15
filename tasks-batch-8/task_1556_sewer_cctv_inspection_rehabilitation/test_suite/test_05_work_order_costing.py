"""Work-order costing: mobilization tiers, per-line rounding, provisional vs final."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line_item,
    approve_plan,
    begin_work,
    create_plan,
    create_technician,
    create_work_order,
    get_plan,
    get_work_order,
    make_crew_lead_headers,
    mobilize,
    propose_plan,
    report_installed,
    setup_certified_segment,
    setup_completed_spot_repair,
    setup_plan_with_work_order,
    validate_error,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def test_mobilization_tier_large_when_both_predicates_fire(api):
    """PRD §3.5: "At the same instant the system derives the work order's
    `mobilization_tier` from the segment's geometry, evaluating the tiers large-first:
    `MOB_LARGE` when the segment's `diameter_mm` is at least 600 millimeters or its
    `length_m` exceeds 300 meters; otherwise `MOB_STANDARD` when the diameter is at
    least 300 millimeters; otherwise `MOB_SMALL`."
    A 700 mm x 400 m segment satisfies both MOB_LARGE predicates; the large-first
    evaluation order makes the result unambiguous.

    Design: Difficulty/combinatorial_formula/mobilization_tier_three_input_nonlinear_mode_a
    """
    ctx = setup_certified_segment(
        material="RCP", diameter_mm=700, length_m=400, install_year=1960,
        defects=[{"pacp_code": "B", "family": "STRUCTURAL", "grade": 4,
                  "distance_m": 50, "clock_position": 12}],
    )
    crew = create_technician(["CREW_LEAD"])
    plan = propose_plan(create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "FULL_REPLACE")["id"])
    plan = approve_plan(plan["id"])  # PRD §3.5: work orders are issued under an APPROVED plan
    resp = api.create_work_order(plan["id"], {"crew_lead_id": crew["id"]}, ENGINEER)
    data = validate_success(resp, 201)
    assert data["mobilization_tier"] == "MOB_LARGE"
    assert data["execution_status"] == "ISSUED"
    assert data["billing_status"] == "UNBILLED"


def test_mobilization_tier_large_fee_joins_cost_rollup(api):
    """PRD §3.5: "The tier keys the mobilization fee that joins every cost rollup:
    900,000 cents (that is, $9,000.00) for `MOB_LARGE`, 400,000 cents ($4,000.00) for
    `MOB_STANDARD`, and 150,000 cents ($1,500.00) for `MOB_SMALL`."
    On the 700 mm x 400 m segment, one 100000-cent line plus the MOB_LARGE fee gives
    a provisional plan total of 1000000.

    Design: Difficulty/combinatorial_formula/mobilization_tier_three_input_nonlinear_mode_a
    """
    ctx = setup_certified_segment(
        material="RCP", diameter_mm=700, length_m=400, install_year=1960,
        defects=[{"pacp_code": "B", "family": "STRUCTURAL", "grade": 4,
                  "distance_m": 50, "clock_position": 12}],
    )
    crew = create_technician(["CREW_LEAD"])
    plan = propose_plan(create_plan(ctx["segment"]["id"], ctx["inspection"]["id"], "FULL_REPLACE")["id"])
    plan = approve_plan(plan["id"])  # PRD §3.5: work orders are issued under an APPROVED plan
    work_order = create_work_order(plan["id"], crew["id"])
    assert get_work_order(work_order["id"])["mobilization_tier"] == "MOB_LARGE"
    add_line_item(work_order["id"], "EXC-CY", 1, 100000)
    assert get_plan(plan["id"])["provisional_total_cents"] == 1000000


def test_per_line_rounding_then_sum_line_values(api):
    """PRD §2.7: "Derived totals obey a pinned rounding order: each line item's value
    is rounded first, half-up to a whole cent, and only then are the rounded line
    values summed."
    PRD §3.5: "Each line immediately earns its `provisional_line_cents`: the scheduled
    quantity multiplied by the unit price, rounded half-up to a whole cent, per line."
    1.5 x 33333 = 49999.5 -> 50000; 1.5 x 33335 = 50002.5 -> 50003;
    1.5 x 33337 = 50005.5 -> 50006.

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_mode_b
    """
    ctx = setup_plan_with_work_order(
        method="SPOT_REPAIR",
        lines=[("L1", 1.5, 33333), ("L2", 1.5, 33335), ("L3", 1.5, 33337)],
        approve=True,
    )
    expected = [50000, 50003, 50006]
    for line, want in zip(ctx["lines"], expected):
        assert line["provisional_line_cents"] == want, (
            f"per-line round_half_up: got {line['provisional_line_cents']}, want {want}"
        )


def test_per_line_rounding_then_sum_plan_total(api):
    """PRD §2.7: "Derived totals obey a pinned rounding order: each line item's value
    is rounded first, half-up to a whole cent, and only then are the rounded line
    values summed." Summing the unrounded products first would yield 300008 here;
    the pinned per-line order yields 150009 of line value plus the MOB_SMALL fee of
    150000, i.e. 300009.

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_mode_b
    """
    ctx = setup_plan_with_work_order(
        method="SPOT_REPAIR",
        lines=[("L1", 1.5, 33333), ("L2", 1.5, 33335), ("L3", 1.5, 33337)],
        approve=True,
    )
    assert get_plan(ctx["plan"]["id"])["provisional_total_cents"] == 300009


def test_provisional_variant_prices_scheduled_quantities(api):
    """PRD §2.7: "The provisional variant, used at proposal and approval time for
    budget commitment, prices every line at its scheduled quantity."
    Lines 2 @ 250000 and 1.5 @ 133333 give 500000 + round_half_up(199999.5) = 700000
    of line value; with the MOB_SMALL fee the provisional total is 850000.

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_invoice_divergence
    """
    ctx = setup_completed_spot_repair(
        lines=[("SPOT-EA", 2, 250000), ("EXC-CY", 1.5, 133333)],
        installed_qtys=[1, 1.7],
    )
    plan = get_plan(ctx["plan"]["id"])
    assert plan["provisional_total_cents"] == 850000


def test_final_variant_diverges_from_provisional(api):
    """PRD §2.7: "The final variant, used at work-order completion and billing,
    prices every line at its field-measured installed quantity and falls back, line by
    line, to the provisional value whenever a line's installed quantity was never
    reported."
    Installed 1 @ 250000 and 1.7 @ 133333 give 250000 + round_half_up(226666.1) =
    476666 of line value; with the MOB_SMALL fee the final total is 626666, diverging
    from the provisional 850000 on identical line items.

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_invoice_divergence
    """
    ctx = setup_completed_spot_repair(
        lines=[("SPOT-EA", 2, 250000), ("EXC-CY", 1.5, 133333)],
        installed_qtys=[1, 1.7],
    )
    plan = get_plan(ctx["plan"]["id"])
    assert plan["final_total_cents"] == 626666
    assert plan["final_total_cents"] != plan["provisional_total_cents"]


def test_provisional_cost_constants_applied_mob_standard_tier(api):
    """PRD §3.5: "At the same instant the system derives the work order's
    `mobilization_tier` from the segment's geometry, evaluating the tiers large-first:
    `MOB_LARGE` when the segment's `diameter_mm` is at least 600 millimeters or its
    `length_m` exceeds 300 meters; otherwise `MOB_STANDARD` when the diameter is at
    least 300 millimeters; otherwise `MOB_SMALL`."
    A 400 mm x 200 m segment lands in MOB_STANDARD; one 250000-cent line plus the
    400000-cent fee gives a provisional total of 650000.

    Design: Corner/calculations/provisional_cost_constants_applied_mob_standard_tier
    """
    ctx = setup_plan_with_work_order(
        method="SPOT_REPAIR", lines=[("SPOT-EA", 1, 250000)], approve=True,
        cert_kwargs={"diameter_mm": 400, "length_m": 200, "install_year": 1972},
    )
    assert ctx["work_order"]["mobilization_tier"] == "MOB_STANDARD"
    assert get_plan(ctx["plan"]["id"])["provisional_total_cents"] == 650000


def test_punch_submit_blocked_until_all_installed_qty_reported(api):
    """PRD §3.5: "submitting the punch list — `IN_WORK` → `PUNCH_LIST` — requires
    every line item to carry a reported `installed_qty` (`ERR_QTY_MISSING`)."

    Design: Corner/endpoints/punch_submit_blocked_until_all_installed_qty_reported
    """
    ctx = setup_plan_with_work_order(
        method="SPOT_REPAIR",
        lines=[("SPOT-EA", 1, 250000), ("EXC-CY", 2, 100000)],
        approve=True,
    )
    wo_id = ctx["work_order"]["id"]
    crew_id = ctx["crew"]["id"]
    mobilize(wo_id, crew_id)
    begin_work(wo_id, crew_id)
    report_installed(wo_id, crew_id, ctx["lines"][0]["id"], 1)  # second line left null
    resp = api.submit_punch(wo_id, make_crew_lead_headers(crew_id))
    validate_error(resp, ApiErrorId.ERR_QTY_MISSING)


def test_error_invoice_before_completion(api):
    """PRD §3.7: "Invoicing moves `UNBILLED` → `INVOICED` and is only possible once
    execution has reached `COMPLETED` (`ERR_NOT_COMPLETED`)."

    Design: Corner/errors/error_invoice_before_completion
    """
    ctx = setup_plan_with_work_order(method="SPOT_REPAIR", lines=None, approve=True)
    mobilize(ctx["work_order"]["id"], ctx["crew"]["id"])
    resp = api.invoice_work_order(ctx["work_order"]["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_NOT_COMPLETED)


def test_billing_regresses_while_execution_stays_completed(api):
    """PRD §3.7: "Invoicing moves `UNBILLED` → `INVOICED` and is only possible once
    execution has reached `COMPLETED` (`ERR_NOT_COMPLETED`). An invoice issued in
    error can be voided back, `INVOICED` → `UNBILLED`, and once the district pays,
    marking paid moves `INVOICED` → `PAID`."
    PRD §3.7: "Because the dimensions are independent, nothing about the billing
    track blocks or accelerates the execution track."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_execution_billing_dimensions
    """
    ctx = setup_completed_spot_repair()
    wo_id = ctx["work_order"]["id"]
    invoiced = validate_success(api.invoice_work_order(wo_id, ENGINEER), 200)
    assert invoiced["billing_status"] == "INVOICED"
    assert invoiced["execution_status"] == "COMPLETED"
    voided = validate_success(api.void_invoice(wo_id, ENGINEER), 200)
    assert voided["billing_status"] == "UNBILLED", "billing regresses INVOICED -> UNBILLED"
    assert voided["execution_status"] == "COMPLETED", "execution dimension is untouched"


def test_billing_paid_after_reinvoice_execution_unchanged(api):
    """PRD §3.7: "An invoice issued in error can be voided back, `INVOICED` →
    `UNBILLED`, and once the district pays, marking paid moves `INVOICED` → `PAID`."
    PRD §3.7: "Because the dimensions are independent, nothing about the billing
    track blocks or accelerates the execution track."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_execution_billing_dimensions
    """
    ctx = setup_completed_spot_repair()
    wo_id = ctx["work_order"]["id"]
    validate_success(api.invoice_work_order(wo_id, ENGINEER), 200)
    validate_success(api.void_invoice(wo_id, ENGINEER), 200)
    validate_success(api.invoice_work_order(wo_id, ENGINEER), 200)
    paid = validate_success(api.mark_paid(wo_id, ENGINEER), 200)
    assert paid["billing_status"] == "PAID"
    assert paid["execution_status"] == "COMPLETED"
