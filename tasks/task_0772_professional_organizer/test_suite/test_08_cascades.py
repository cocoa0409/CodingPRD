"""Depth-3 lifecycle cascades: project cancellation and invoice payment."""
from test_helpers import (
    validate_success, assert_version_incremented,
    new_active_project, new_product_line,
    setup_paid_ready_with_maintenance_plan,
    make_organizer_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ── Difficulty: project cancel cascade (project -> product line -> ledger) ─────

def test_project_cancel_cascades_to_product_line_and_ledger(api):
    """PRD §3.8: "every product line still in QUOTED or ORDERED is moved to
    CANCELLED, and each such cancellation subtracts that line's client_price_cents
    from the project's projected_product_cost_cents ledger"
    PRD §3.8: "Cancellation moves the project to CANCELLED, increments its version by
    one, and fans out to its dependents"

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth3
    """
    client, organizer, project = new_active_project(scope_rooms=["Den"])
    line = new_product_line(project["id"], organizer["id"],
                            wholesale_cost_cents=1099, quantity=3, markup_pct=0.35)  # 4452
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["projected_product_cost_cents"] == 4452

    cancelled = validate_success(api.cancel_project(project["id"], OM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["projected_product_cost_cents"] == 0

    line_after = validate_success(api.get_product_line(line["id"], OM), 200)
    assert line_after["status"] == "CANCELLED"


def test_project_cancel_cascades_to_ordered_lines_and_zeroes_ledger(api):
    """PRD §3.8: "every product line still in QUOTED or ORDERED is moved to
    CANCELLED, and each such cancellation subtracts that line's client_price_cents
    from the project's projected_product_cost_cents ledger"

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth3
    """
    client, organizer, project = new_active_project(scope_rooms=["Den"])
    org_headers = make_organizer_headers(organizer["id"])
    quoted = new_product_line(project["id"], organizer["id"],
                              wholesale_cost_cents=1099, quantity=3, markup_pct=0.35)  # 4452
    ordered = new_product_line(project["id"], organizer["id"],
                               wholesale_cost_cents=1000, quantity=1, markup_pct=0.0)  # 1000
    validate_success(api.patch_product_line(ordered["id"], {"status": "ORDERED"}, org_headers), 200)
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["projected_product_cost_cents"] == 5452

    cancelled = validate_success(api.cancel_project(project["id"], OM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["projected_product_cost_cents"] == 0
    assert validate_success(api.get_product_line(quoted["id"], OM), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_product_line(ordered["id"], OM), 200)["status"] == "CANCELLED"


# ── Difficulty: invoice pay cascade (invoice -> project close -> plan activate) ─

def test_invoice_payment_closes_project_and_activates_plan(api):
    """PRD §3.8: "Paying an invoice, done by a Client or a BillingAdmin, advances it
    from ISSUED to PAID and sets off a cascade. Payment closes the parent project,
    moving it from WRAP_UP to CLOSED. If that project has a maintenance plan sitting
    in DRAFT, closure in turn activates it, transitioning the plan from DRAFT to
    ACTIVE."

    Design: Difficulty/transitive_cascade/invoice_pay_cascade_depth3
    """
    client, organizer, project, plan, invoice = setup_paid_ready_with_maintenance_plan()
    paid = validate_success(api.pay_invoice(invoice["id"], BA), 200)
    assert paid["status"] == "PAID"
    assert validate_success(api.get_project(project["id"], OM), 200)["status"] == "CLOSED"
    assert validate_success(api.get_maintenance_plan(plan["id"], OM), 200)["status"] == "ACTIVE"


def test_invoice_payment_activation_increments_plan_version(api):
    """PRD §3.8: "If that project has a maintenance plan sitting in DRAFT, closure in
    turn activates it, transitioning the plan from DRAFT to ACTIVE. Each of these
    transitions is a distinct mutation that refreshes the affected resource's
    updated_at and increments its version."

    Design: Difficulty/transitive_cascade/invoice_pay_cascade_depth3
    """
    client, organizer, project, plan, invoice = setup_paid_ready_with_maintenance_plan()
    plan_before = validate_success(api.get_maintenance_plan(plan["id"], OM), 200)
    assert plan_before["status"] == "DRAFT"

    validate_success(api.pay_invoice(invoice["id"], BA), 200)

    plan_after = validate_success(api.get_maintenance_plan(plan["id"], OM), 200)
    assert plan_after["status"] == "ACTIVE"
    assert_version_incremented(plan_after["version"], plan_before["version"])
