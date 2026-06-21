"""Repair orders: flat-rate labor tiers, the parallel work/billing dimensions,
the empty-service-line guard, the work-complete invoice guard, the authorization
ceiling with dealer override, and the state-beats-fiscal priority conflict.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_service_line_payload, TEST_USERS,
    setup_repair_order, setup_started_repair_order, setup_completed_repair_order,
)

SA = TEST_USERS["service_advisor_headers"]
DP = TEST_USERS["dealer_principal_headers"]


def test_labor_total_tiered_with_shop_supply_cap(api):
    """PRD 3.7: "if the total is greater than 2.0 hours but at most 6.0 hours, the
    rate is the base less a 1000-cent discount, that is 11500 cents per hour."
    PRD 3.7: "labor_total_cents is the sum over service lines of each line's
    flat_rate_hours multiplied by the effective rate and rounded half up per line
    before summation."

    Design: Difficulty/combinatorial_formula/ro_labor_total_tier_warranty_cap_nonlinear
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(3.0, 1.5), is_warranty=False,
        authorized_amount_cents=100_000)
    assert ro["work_status"] == "WORK_COMPLETE"
    # 4.5h -> tier2 rate 11500: round(3.0*11500)=34500 + round(1.5*11500)=17250 = 51750
    assert ro["labor_total_cents"] == 51750


def test_shop_supplies_capped_at_fifty_dollars(api):
    """PRD 3.7: "For a non-warranty order it is 800 basis points (8 percent) of
    labor_total_cents: multiply the labor total by 800, divide by 10000, round half
    up, and then cap the result at 5000 cents ($50.00) — the fee is the lesser of
    that rounded 8 percent and the 5000-cent cap."

    Design: Difficulty/combinatorial_formula/ro_labor_total_tier_warranty_cap_nonlinear
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(3.0, 1.5), is_warranty=False,
        authorized_amount_cents=100_000)
    # 8% of 51750 = round(4140) = 4140, below the 5000 cap
    assert ro["shop_supplies_cents"] == 4140


def test_parallel_work_and_billing_dimensions(api):
    """PRD 3.6: "On creation the repair order's work_status is OPEN and its
    billing_status is UNBILLED."
    PRD 3.6: "Completing work advances IN_PROGRESS to WORK_COMPLETE."
    PRD 3.6: "The billing dimension, billing_status, evolves independently of work
    and runs UNBILLED, INVOICED, PAID, with VOID as its terminal state."

    Design: Difficulty/non_linear_state_machine/repair_order_parallel_work_and_billing_dimensions
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(2.0,), authorized_amount_cents=50_000)
    assert ro["work_status"] == "WORK_COMPLETE"
    assert ro["billing_status"] == "UNBILLED"


def test_billing_stays_unbilled_through_work_completion(api):
    """PRD 3.6: "Although INVOICED depends on the work-state being WORK_COMPLETE,
    the two fields are otherwise separate and are reported separately."

    Design: Difficulty/non_linear_state_machine/repair_order_parallel_work_and_billing_dimensions
    """
    cust, unit, tech, ro, lines = setup_started_repair_order(
        flat_rate_hours_list=(2.0,), authorized_amount_cents=50_000)
    assert ro["work_status"] == "IN_PROGRESS"
    assert ro["billing_status"] == "UNBILLED"
    completed = validate_success(api.complete_repair_order(ro["id"], SA), 200)
    assert completed["work_status"] == "WORK_COMPLETE"
    assert completed["billing_status"] == "UNBILLED"


def test_start_rejected_on_empty_service_line_set(api):
    """PRD 3.6: "Starting work advances OPEN to IN_PROGRESS and requires that at
    least one ServiceLine already exist on the order, otherwise it is rejected with
    ERR_NO_SERVICE_LINES."

    Design: Difficulty/boundary_precision_check/ro_start_rejected_on_empty_service_line_set
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[], authorized_amount_cents=50_000)
    res = api.start_repair_order(ro["id"], SA)
    validate_error(res, "ERR_NO_SERVICE_LINES")


def test_start_with_one_service_line_succeeds(api):
    """PRD 3.6: "Starting work advances OPEN to IN_PROGRESS and requires that at
    least one ServiceLine already exist on the order, otherwise it is rejected with
    ERR_NO_SERVICE_LINES."

    Design: Difficulty/boundary_precision_check/ro_start_rejected_on_empty_service_line_set
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[1.0], authorized_amount_cents=50_000)
    started = validate_success(api.start_repair_order(ro["id"], SA), 200)
    assert started["work_status"] == "IN_PROGRESS"


def test_invoice_requires_work_complete(api):
    """PRD 3.6: "Invoicing moves UNBILLED to INVOICED but requires the work
    dimension to have reached WORK_COMPLETE, otherwise it is rejected with
    ERR_WORK_NOT_COMPLETE."

    Design: Corner/state_machines/ro_invoice_requires_work_complete_guard
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[1.0], authorized_amount_cents=50_000)
    res = api.invoice_repair_order(ro["id"], SA)
    validate_error(res, "ERR_WORK_NOT_COMPLETE")


def test_invoice_state_guard_beats_fiscal_over_authorization(api):
    """PRD 2.8: "The state-machine from-state check follows ... After the from-state
    check come any cross-entity precondition on a referenced sibling resource, then
    the domain-specific safety, temporal, stock, and fiscal rules described in
    Section 3."
    PRD 3.6: "Invoicing moves UNBILLED to INVOICED but requires the work dimension
    to have reached WORK_COMPLETE, otherwise it is rejected with
    ERR_WORK_NOT_COMPLETE."

    Design: Difficulty/priority_pair_validation_conflict/ro_invoice_state_beats_fiscal_over_authorization
    """
    # 3.0h retail labor (51750) would exceed authorized 10000, but work is only
    # IN_PROGRESS, so the work-not-complete state error must pre-empt the fiscal one.
    cust, unit, tech, ro, lines = setup_started_repair_order(
        flat_rate_hours_list=(3.0,), authorized_amount_cents=10_000)
    res = api.invoice_repair_order(ro["id"], SA)
    validate_error(res, "ERR_WORK_NOT_COMPLETE")


def test_invoice_state_guard_leaves_billing_unbilled(api):
    """PRD 3.6: "Invoicing moves UNBILLED to INVOICED but requires the work
    dimension to have reached WORK_COMPLETE, otherwise it is rejected with
    ERR_WORK_NOT_COMPLETE."
    PRD 2.8: "The state-machine from-state check follows ... After the from-state
    check come any cross-entity precondition on a referenced sibling resource, then
    the domain-specific safety, temporal, stock, and fiscal rules described in
    Section 3."

    Design: Difficulty/priority_pair_validation_conflict/ro_invoice_state_beats_fiscal_over_authorization
    """
    cust, unit, tech, ro, lines = setup_started_repair_order(
        flat_rate_hours_list=(3.0,), authorized_amount_cents=10_000)
    res = api.invoice_repair_order(ro["id"], SA)
    validate_error(res, "ERR_WORK_NOT_COMPLETE")
    ro_after = validate_success(api.get_repair_order(ro["id"], SA), 200)
    assert ro_after["billing_status"] == "UNBILLED"


def test_over_authorization_invoice_rejected_for_service_advisor(api):
    """PRD 3.8: "At invoice time, for a non-warranty order, the platform compares
    the finalized ro_total_cents against this ceiling: if the total exceeds the
    authorized amount, the invoice is blocked with ERR_OVER_AUTHORIZATION (HTTP
    402) unless the caller is a DealerPrincipal, who holds override authority and
    may invoice over the authorized amount."

    Design: Corner/validations/over_authorization_invoice_rejected_for_service_advisor
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(3.0,), authorized_amount_cents=10_000)
    res = api.invoice_repair_order(ro["id"], SA)
    validate_error(res, "ERR_OVER_AUTHORIZATION")
    ro_after = validate_success(api.get_repair_order(ro["id"], SA), 200)
    assert ro_after["billing_status"] == "UNBILLED"


def test_dealer_principal_overrides_over_authorization(api):
    """PRD 3.8: "if the total exceeds the authorized amount, the invoice is blocked
    with ERR_OVER_AUTHORIZATION (HTTP 402) unless the caller is a DealerPrincipal,
    who holds override authority and may invoice over the authorized amount."

    Design: Corner/validations/dealer_principal_override_invoices_over_authorization
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(3.0,), authorized_amount_cents=10_000)
    invoiced = validate_success(api.invoice_repair_order(ro["id"], DP), 200)
    assert invoiced["billing_status"] == "INVOICED"


def test_cancel_open_ro_voids_billing(api):
    """PRD 3.6: "cancellation moves work_status from OPEN or IN_PROGRESS to the
    terminal CANCELLED, releases every RESERVED part line on the order ... and — as
    a coupled effect on the other dimension — voids the billing."
    PRD 3.6: "When the work dimension is cancelled, the billing dimension is
    automatically driven from UNBILLED to the terminal VOID by the same operation."

    Design: Corner/state_machines/ro_cancel_voids_billing_dimension
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[1.0], authorized_amount_cents=50_000)
    cancelled = validate_success(api.cancel_repair_order(ro["id"], SA), 200)
    assert cancelled["work_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "VOID"


def test_cancel_after_invoiced_rejected(api):
    """PRD 3.6: "Cancelling a repair order is permitted only while its
    billing_status is still UNBILLED, otherwise it is rejected with
    ERR_RO_ALREADY_BILLED."

    Design: Corner/state_machines/ro_cancel_after_billed_returns_already_billed
    """
    cust, unit, tech, ro, lines = setup_completed_repair_order(
        flat_rate_hours_list=(1.0,), authorized_amount_cents=50_000)
    validate_success(api.invoice_repair_order(ro["id"], SA), 200)
    res = api.cancel_repair_order(ro["id"], SA)
    validate_error(res, "ERR_RO_ALREADY_BILLED")
    ro_after = validate_success(api.get_repair_order(ro["id"], SA), 200)
    assert ro_after["work_status"] == "WORK_COMPLETE"
    assert ro_after["billing_status"] == "INVOICED"
