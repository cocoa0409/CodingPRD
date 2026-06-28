"""Multi-hop cascades (plan-cancel, invoice-void) and conserved-quantity invariants
(technician scheduled_minutes, customer outstanding_balance_cents), plus the derived-balance
reconciliations and atomic completion. Translates Difficulty rules transitive_cascade and
compensating_invariant and the derived_field_reconciliation / consistency corner instances.
"""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId, validate_error,
    setup_accepted_quote, setup_completed_visit,
    create_clear_weather_window, create_technician, create_plan, generate_plan_visit,
    schedule_visit, reserve_crew, confirm_crew, get_invoice_for_visit, set_clock,
    make_customer_headers,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade
# ─────────────────────────────────────────────────────────────────────────

def test_plan_cancel_cascades_to_visit_assignment_and_tech_minutes(api):
    """PRD §3.9: "First, the plan moves to the terminal `CANCELLED` status. Second, every
    visit under the plan that is still `REQUESTED` or `SCHEDULED` is moved to `CANCELLED`.
    Third, each of those cancelled visits' `RESERVED` and `CONFIRMED` crew assignments is
    moved to `RELEASED`, each release decrementing the relevant technician's
    `scheduled_minutes`."

    Design: Difficulty/transitive_cascade/plan_cancel_cascade_depth3_plan_visit_assignment_minutes
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    create_clear_weather_window(ctx["route"]["id"])
    tech = create_technician()
    plan = create_plan(ctx["property"]["id"], ctx["quote"]["id"], cadence_days=30)
    visit = generate_plan_visit(plan["id"], duration_minutes=120)
    visit = schedule_visit(visit["id"], visit["version"])
    asg = confirm_crew(reserve_crew(visit["id"], tech["id"], "2026-05-01T14:00:00Z")["id"])
    # Precondition: tech committed 120 minutes.
    assert get_success_data(api.get_technician(tech["id"], DISP))["scheduled_minutes"] == 120

    cancelled = validate_success(api.cancel_plan(plan["id"], DISP), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert get_success_data(api.get_visit(visit["id"], DISP))["status"] == "CANCELLED"
    assert get_success_data(api.get_assignment(asg["id"], DISP))["status"] == "RELEASED"
    assert get_success_data(api.get_technician(tech["id"], DISP))["scheduled_minutes"] == 0


def test_invoice_void_cascades_to_visit_billing_and_balance(api):
    """PRD §3.8: "Voiding has a three-part cascade: the invoice moves to `VOIDED`; the linked
    visit's `billing_status` is set to `VOIDED`; and the customer's `outstanding_balance_cents`
    is recomputed to drop this invoice's `amount_due_cents`, restoring the balance to exactly
    the value it held before the invoice was issued."

    Design: Difficulty/transitive_cascade/invoice_void_cascade_depth3_invoice_visit_customer_balance
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2000, re_measured_siding_sqft=1500,
        route_overrides={"travel_buffer_minutes": 0},
    )
    inv = ctx["invoice"]
    cust_id = ctx["customer"]["id"]
    voided = validate_success(api.void_invoice(inv["id"], BILL), 200)
    assert voided["status"] == "VOIDED", voided["status"]
    assert get_success_data(api.get_visit(ctx["visit"]["id"], DISP))["billing_status"] == "VOIDED"
    bal = get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"]
    assert bal == 0, bal


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant
# ─────────────────────────────────────────────────────────────────────────

def test_tech_minutes_conserved_reserve_then_release(api):
    """PRD §2.9: "A technician's `scheduled_minutes` is a derived, conserved quantity: it
    always equals the sum of the `duration_minutes` of that technician's crew assignments
    whose status is `RESERVED` or `CONFIRMED`. Reserving an assignment increases it; releasing
    an assignment decreases it by exactly that assignment's `duration_minutes`."

    Design: Difficulty/compensating_invariant/tech_minutes_conserved_reserve_then_release
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    create_clear_weather_window(ctx["route"]["id"])
    tech = create_technician()
    from test_helpers import create_visit
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01",
                         duration_minutes=120)
    visit = schedule_visit(visit["id"], visit["version"])
    asg = reserve_crew(visit["id"], tech["id"], "2026-05-01T14:00:00Z")
    assert get_success_data(api.get_technician(tech["id"], DISP))["scheduled_minutes"] == 120
    released = validate_success(api.release_assignment(asg["id"], DISP), 200)
    assert released["status"] == "RELEASED", released["status"]
    assert get_success_data(api.get_technician(tech["id"], DISP))["scheduled_minutes"] == 0


def test_invoice_balance_conserved_issue_then_void(api):
    """PRD §2.9: "A customer's `outstanding_balance_cents` is likewise derived: it is the sum
    of `amount_due_cents` across that customer's invoices whose status is `ISSUED` or
    `DISPUTED` ... When an invoice is voided, the balance returns to exactly the value it held
    before that invoice was issued."

    Design: Difficulty/compensating_invariant/invoice_balance_conserved_issue_then_void
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2000, re_measured_siding_sqft=1500,
        route_overrides={"travel_buffer_minutes": 0},
    )
    inv = ctx["invoice"]
    cust_id = ctx["customer"]["id"]
    assert inv["amount_due_cents"] == 92750, inv["amount_due_cents"]
    bal_before = get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"]
    assert bal_before == 92750, bal_before
    validate_success(api.void_invoice(inv["id"], BILL), 200)
    bal_after = get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"]
    assert bal_after == 0, bal_after


# ─────────────────────────────────────────────────────────────────────────
# Corner / derived_field_reconciliation + consistency
# ─────────────────────────────────────────────────────────────────────────

def test_outstanding_balance_drops_to_zero_on_pay(api):
    """PRD §3.8: "A `BillingAdmin` records payment on an `ISSUED` invoice, moving it to the
    terminal `PAID` status; this is legal only from `ISSUED` (otherwise `ERR_INVALID_STATE`)
    and recomputes the customer's `outstanding_balance_cents`, from which paid invoices drop
    out."

    Design: Corner/cross_cutting_complexity_layers/derived_outstanding_balance_recomputed_on_pay
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2000, re_measured_siding_sqft=1500,
        route_overrides={"travel_buffer_minutes": 0},
    )
    inv = ctx["invoice"]
    cust_id = ctx["customer"]["id"]
    assert get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"] == 92750
    validate_success(api.pay_invoice(inv["id"], BILL), 200)
    assert get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"] == 0


def test_dispute_keeps_outstanding_balance_unchanged(api):
    """PRD §3.8: "A `Customer` who owns an invoice may dispute it while it is `ISSUED`, moving
    it to `DISPUTED` ... it leaves `outstanding_balance_cents` unchanged because a disputed
    invoice remains in the balance sum."

    Design: Corner/cross_cutting_complexity_layers/dispute_keeps_outstanding_balance_unchanged
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2000, re_measured_siding_sqft=1500,
        route_overrides={"travel_buffer_minutes": 0},
    )
    inv = ctx["invoice"]
    cust_id = ctx["customer"]["id"]
    disputed = validate_success(
        api.dispute_invoice(inv["id"], make_customer_headers(cust_id)), 200)
    assert disputed["status"] == "DISPUTED", disputed["status"]
    assert get_success_data(api.get_customer(cust_id, DISP))["outstanding_balance_cents"] == 92750


def test_complete_visit_atomically_bills_and_raises_balance(api):
    """PRD §3.8: "Completing a visit auto-issues exactly one `Invoice` for that single visit
    — billing is strictly per visit ... On issuance the visit's `billing_status` flips to
    `BILLED` and the owning customer's `outstanding_balance_cents` is recomputed."

    Design: Corner/consistency_model/complete_visit_atomic_invoice_and_balance_in_same_request
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2000, re_measured_siding_sqft=1500,
        route_overrides={"travel_buffer_minutes": 0},
    )
    completed = ctx["completed_visit"]
    assert completed["final_cost_cents"] == 92750, completed["final_cost_cents"]
    assert completed["billing_status"] == "BILLED", completed["billing_status"]
    inv = ctx["invoice"]
    assert inv is not None and inv["amount_due_cents"] == 92750, inv
    bal = get_success_data(api.get_customer(ctx["customer"]["id"], DISP))["outstanding_balance_cents"]
    assert bal == 92750, bal
