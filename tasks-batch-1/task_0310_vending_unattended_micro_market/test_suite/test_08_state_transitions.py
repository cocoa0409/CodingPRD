"""State-machine transitions and lockdowns: invalid transitions and precondition
enforcement across visits, tickets, routes, statements, and sales, plus the
cross-entity unfreeze and the cash-collection reset.
"""
from test_helpers import validate_success, validate_error, api_client, counted_line
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_sale,
    make_statement, make_ticket, machine_version,
)
from test_helpers.test_users import TEST_USERS, make_route_driver_headers

FIELD_OPS = TEST_USERS["field_ops_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


# ─── Corner/state_machines/reconcile_already_reconciled_visit_returns_not_draft ─

def test_reconcile_already_reconciled_visit_rejected():
    """PRD §3.5: "Reconciling a visit is a RouteDriver action that advances the
    visit DRAFT -> RECONCILED. ... the visit itself to still be DRAFT, or it is
    rejected with ERR_VISIT_NOT_DRAFT (HTTP 409)".

    Design: Corner/state_machines/reconcile_already_reconciled_visit_returns_not_draft
    """
    set_clock("2026-06-21T00:00:00Z")
    host = make_host(name="Hr", contact_email="hr@x.com")
    prod = make_product(sku="RC", name="Rc", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="RCT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="R1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Rc Drv", employee_code="EMPR")
    route = make_route(driver["id"], "2026-06-21T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    # Second reconcile (visit now RECONCILED). Use the current machine version so
    # the visit-state check is what fails, not the OCC version check.
    vnow = machine_version(machine["id"])
    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": vnow}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_VISIT_NOT_DRAFT", expected_status=409)


# ─── Corner/state_machines/start_ticket_not_open_returns_not_open ──────────

def test_start_in_progress_ticket_rejected():
    """PRD §3.8: "A FieldOps operator starts work on a ticket, which advances it
    OPEN -> IN_PROGRESS; this requires the ticket to be OPEN, or it is rejected
    with ERR_TICKET_NOT_OPEN."

    Design: Corner/state_machines/start_ticket_not_open_returns_not_open
    """
    host = make_host(name="Ht", contact_email="ht@x.com")
    machine = make_machine(host["id"], asset_tag="TKT", machine_type="SNACK_VENDOR")
    ticket = make_ticket(machine["id"], issue_type="JAM")
    validate_success(api_client.start_ticket(ticket["id"], FIELD_OPS), 200)
    res = api_client.start_ticket(ticket["id"], FIELD_OPS)
    validate_error(res, "ERR_TICKET_NOT_OPEN", expected_status=409)


# ─── Corner/state_machines/dispatch_empty_route_returns_route_empty ────────

def test_dispatch_empty_route_rejected():
    """PRD §3.4: "Dispatch requires that the route have at least one stop, or it
    is rejected with ERR_ROUTE_EMPTY (HTTP 409)".

    Design: Corner/state_machines/dispatch_empty_route_returns_route_empty
    """
    driver = make_driver(full_name="Empty Drv", employee_code="EMPE")
    route = make_route(driver["id"], "2026-06-22T00:00:00Z")
    res = api_client.dispatch_route(route["id"], FIELD_OPS)
    validate_error(res, "ERR_ROUTE_EMPTY", expected_status=409)


# ─── Corner/state_machines/close_route_with_unresolved_stop_returns_stops_unresolved ─

def test_close_route_with_unresolved_stop_rejected():
    """PRD §3.4: "Closing requires that every stop be either VISITED or SKIPPED;
    if any stop remains unresolved the close is rejected with
    ERR_STOPS_UNRESOLVED (HTTP 409)."

    Design: Corner/state_machines/close_route_with_unresolved_stop_returns_stops_unresolved
    """
    host = make_host(name="Hu", contact_email="hu@x.com")
    machine = make_machine(host["id"], asset_tag="URT", machine_type="SNACK_VENDOR")
    driver = make_driver(full_name="U Drv", employee_code="EMPU")
    route = make_route(driver["id"], "2026-06-23T00:00:00Z")
    make_stop(route["id"], machine["id"])
    dispatch(route["id"])  # stop is now KITTED, never visited.
    res = api_client.close_route(route["id"], FIELD_OPS)
    validate_error(res, "ERR_STOPS_UNRESOLVED", expected_status=409)


# ─── Corner/state_machines/finalize_already_finalized_statement_returns_not_open ─

def test_finalize_already_finalized_statement_rejected():
    """PRD §3.7: "Finalizing a statement is a FinanceClerk action that advances
    OPEN -> FINALIZED. It requires the statement to be OPEN, or it is rejected with
    ERR_STATEMENT_NOT_OPEN".

    Design: Corner/state_machines/finalize_already_finalized_statement_returns_not_open
    """
    set_clock("2026-06-24T00:00:00Z")
    host = make_host(name="Hf", contact_email="hf@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10)
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    res = api_client.finalize_statement(statement["id"], FINANCE)
    validate_error(res, "ERR_STATEMENT_NOT_OPEN", expected_status=409)


# ─── Corner/state_machines/finalize_blocked_while_draft_visit_pending ──────

def test_finalize_blocked_by_pending_draft_visit():
    """PRD §3.7: "it requires that no restock visit on this host's machines within
    the period still be in DRAFT, or it is rejected with ERR_VISITS_PENDING (HTTP
    409)."

    Design: Corner/state_machines/finalize_blocked_while_draft_visit_pending
    """
    set_clock("2026-06-25T00:00:00Z")
    host = make_host(name="Hp", contact_email="hp@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10)
    prod = make_product(sku="PD", name="Pd", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="PDT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="PD1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Pd Drv", employee_code="EMPP")
    route = make_route(driver["id"], "2026-06-25T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    # Open a DRAFT visit but do NOT reconcile it.
    open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    res = api_client.finalize_statement(statement["id"], FINANCE)
    validate_error(res, "ERR_VISITS_PENDING", expected_status=409)


# ─── Corner/state_machines/void_already_void_sale_returns_not_settled ──────

def test_void_already_void_sale_rejected():
    """PRD §3.6: "A settled sale may be voided by a FieldOps operator, which
    advances the sale SETTLED -> VOID; it requires the sale's settlement_status to
    be SETTLED, or it is rejected with ERR_SALE_NOT_SETTLED (HTTP 409)."

    Design: Corner/state_machines/void_already_void_sale_returns_not_settled
    """
    set_clock("2026-06-26T00:00:00Z")
    host = make_host(name="Hv", contact_email="hv@x.com")
    prod = make_product(sku="VD", name="Vd", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="VDT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="V1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Vd Drv", employee_code="EMPV")
    route = make_route(driver["id"], "2026-06-26T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    sale = make_sale(machine["id"], slot["id"], 1, "CASHLESS")
    validate_success(api_client.void_sale(sale["id"], FIELD_OPS), 200)
    res = api_client.void_sale(sale["id"], FIELD_OPS)
    validate_error(res, "ERR_SALE_NOT_SETTLED", expected_status=409)


# ─── Corner/state_machines/machine_unfreezes_when_blocking_ticket_resolved ─

def test_machine_unfreezes_when_blocking_ticket_resolved():
    """PRD §3.8: "A FieldOps operator resolves an in-progress ticket, advancing it
    IN_PROGRESS -> RESOLVED; ... and on resolution, if no other blocking ticket
    remains in OPEN, IN_PROGRESS, or REOPENED on the machine, the machine's
    service_status returns to IN_SERVICE."

    Design: Corner/state_machines/machine_unfreezes_when_blocking_ticket_resolved
    """
    host = make_host(name="Hz", contact_email="hz@x.com")
    machine = make_machine(host["id"], asset_tag="FZT", machine_type="SNACK_VENDOR")
    ticket = make_ticket(machine["id"], issue_type="COIN_MECH", blocking=True)
    validate_success(api_client.start_ticket(ticket["id"], FIELD_OPS), 200)
    frozen = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert frozen["service_status"] == "FROZEN", frozen

    resolved = validate_success(api_client.resolve_ticket(ticket["id"], FIELD_OPS), 200)
    assert resolved["status"] == "RESOLVED", resolved
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["service_status"] == "IN_SERVICE", after


# ─── Corner/state_machines/cash_collection_resets_vault_and_cash_status ────

def test_cash_collection_resets_vault_and_status():
    """PRD §3.2: "When a FieldOps operator records a cash collection, the vault's
    cash_on_hand_cents is reset to 0 and the machine transitions CASH_FULL_WARN ->
    CASH_OK".

    Design: Corner/state_machines/cash_collection_resets_vault_and_cash_status
    """
    set_clock("2026-06-27T00:00:00Z")
    host = make_host(name="Hk", contact_email="hk@x.com")
    prod = make_product(sku="CK", name="Ck", category="BEVERAGE", unit_cost_cents=4000)
    machine = make_machine(host["id"], asset_tag="CKT", machine_type="BEVERAGE_VENDOR",
                           cash_capacity_cents=50000, cash_alert_threshold_pct=0.80)
    slot = make_slot(machine["id"], prod["id"], slot_code="CK1",
                     capacity=10, par_level=10, price_cents=20000)
    driver = make_driver(full_name="Ck Drv", employee_code="EMPK")
    route = make_route(driver["id"], "2026-06-27T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    make_sale(machine["id"], slot["id"], 2, "CASH")  # 40000 -> CASH_FULL_WARN
    warned = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert warned["cash_status"] == "CASH_FULL_WARN", warned

    collected = validate_success(api_client.collect_cash(machine["id"], FIELD_OPS), 200)
    assert collected["cash_on_hand_cents"] == 0, collected
    assert collected["cash_status"] == "CASH_OK", collected
