"""Listing/pagination envelope, error envelope shape, RBAC enforcement, and the
optimistic-concurrency stale-machine-version guard on reconcile.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, api_client, counted_line,
    MISSING_UUID,
)
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile,
)
from test_helpers.test_users import (
    TEST_USERS, make_route_driver_headers, make_host_manager_headers,
)

FIELD_OPS = TEST_USERS["field_ops_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]
HOST_MANAGER = TEST_USERS["host_manager_headers"]
ROUTE_DRIVER = TEST_USERS["route_driver_headers"]


# ─── Corner/endpoints/list_machines_pagination_envelope ────────────────────

def test_list_machines_pagination_envelope():
    """PRD §2.3: "Every list-based response includes the following fields in the
    meta object of the response envelope: limit, offset, total_count, and
    has_more."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Two machines exist -> total_count 2 and has_more false under the default
    limit of 10.

    Design: Corner/endpoints/list_machines_pagination_envelope
    """
    host = make_host(name="Hl", contact_email="hl@x.com")
    make_machine(host["id"], asset_tag="L1", machine_type="SNACK_VENDOR")
    make_machine(host["id"], asset_tag="L2", machine_type="SNACK_VENDOR")

    res = api_client.list_machines(HOST_MANAGER)
    data, meta = validate_paginated(res)
    assert res.json()["response_type"] == "array", res.json()
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta


# ─── Corner/errors/error_envelope_shape_on_not_found ───────────────────────

def test_error_envelope_shape_on_slot_not_found():
    """PRD §2.6: "the system validates existence left-to-right and rejects the
    request at the first identifier that does not resolve, returning the not-found
    error specific to that resource type — ... ERR_SLOT_NOT_FOUND ... each carrying
    HTTP 404."
    PRD §2.2: "The error_id is a unique, machine-readable string that identifies
    the specific error. The message provides a human-readable explanation of what
    went wrong."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    res = api_client.get_slot(MISSING_UUID, FIELD_OPS)
    error_data = validate_error(res, "ERR_SLOT_NOT_FOUND", expected_status=404)
    body = res.json()
    assert body["response_type"] == "error", body
    assert isinstance(error_data["message"], str) and len(error_data["message"].strip()) > 0, error_data


# ─── Corner/rbac/routedriver_cannot_create_machine ─────────────────────────

def test_route_driver_cannot_create_machine():
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §2.1: "FieldOps is the operations technician who provisions the catalog,
    places machines, configures slots".

    Placing a machine is FieldOps-only; a RouteDriver attempt is forbidden.

    Design: Corner/rbac/routedriver_cannot_create_machine
    """
    host = make_host(name="Hrb", contact_email="hrb@x.com")
    res = api_client.create_machine(
        {"host_site_id": host["id"], "asset_tag": "RBT", "machine_type": "SNACK_VENDOR"},
        make_route_driver_headers("00000000-0000-4000-8000-000000000abc"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner/rbac/financeclerk_cannot_open_service_ticket ───────────────────

def test_finance_clerk_cannot_open_service_ticket():
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §3.8: "A service ticket is opened against a machine by a FieldOps operator
    or a HostManager."

    FinanceClerk is not among the permitted openers.

    Design: Corner/rbac/financeclerk_cannot_open_service_ticket
    """
    host = make_host(name="Hrc", contact_email="hrc@x.com")
    machine = make_machine(host["id"], asset_tag="RCT2", machine_type="SNACK_VENDOR")
    res = api_client.create_ticket(machine["id"], {"issue_type": "JAM"}, FINANCE)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner/rbac/hostmanager_can_record_sale_shared_op ─────────────────────

def test_host_manager_can_record_sale():
    """PRD §2.1: "HostManager is host-site staff who view their own statements,
    open service tickets, and record sales at the kiosk."
    PRD §3.6: "A sale is recorded by a FieldOps operator or a HostManager (the
    host's own kiosk staff)."

    Design: Corner/rbac/hostmanager_can_record_sale_shared_op
    """
    set_clock("2026-06-30T00:00:00Z")
    host = make_host(name="Hsh", contact_email="hsh@x.com")
    prod = make_product(sku="SH", name="Sh", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="SHT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="SH1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Sh Drv", employee_code="EMPSH")
    route = make_route(driver["id"], "2026-06-30T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])

    # HostManager identity is the acting host site id (entity_backed:HostSite).
    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 1, "payment_method": "CASHLESS"},
        make_host_manager_headers(host["id"]))
    sale = validate_success(res, 201)
    assert sale["gross_cents"] == 100, sale


# ─── Corner/cross_cutting_complexity_layers/occ_stale_machine_version_on_reconcile_returns_412 ─

def test_stale_machine_version_on_reconcile_rejected():
    """PRD §2.10: "At reconcile time the system compares expected_machine_version
    to the machine's current version. If another writer has advanced the machine's
    version since the driver last read it — for example, a sale-driven posture
    change or an earlier reconcile — the values no longer match, and the reconcile
    is rejected with ERR_STALE_MACHINE_VERSION (HTTP 412)."

    Two DRAFT visits hold the pre-reconcile version; the first reconcile bumps
    Machine.version, so the second carrying the stale version is refused.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_machine_version_on_reconcile_returns_412
    """
    set_clock("2026-06-18T00:00:00Z")
    host = make_host(name="Hocc", contact_email="hocc@x.com")
    prod = make_product(sku="OC", name="Oc", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="OCT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="OC1",
                     capacity=40, par_level=40, price_cents=100)
    driver = make_driver(full_name="Oc Drv", employee_code="EMPOC")
    route = make_route(driver["id"], "2026-06-18T00:00:00Z")
    stop1 = make_stop(route["id"], machine["id"], 480, 540)
    stop2 = make_stop(route["id"], machine["id"], 600, 660)
    dispatch(route["id"])
    v0 = machine["version"]
    visit1 = open_visit(stop1["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    visit2 = open_visit(stop2["id"], [counted_line(slot["id"], 0, 5)], v0, driver["id"])
    # First reconcile bumps Machine.version away from v0.
    reconcile(visit1["id"], v0, driver["id"])
    # Second reconcile still carries the stale v0.
    res = api_client.reconcile_visit(
        visit2["id"], {"expected_machine_version": v0}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_STALE_MACHINE_VERSION", expected_status=412)
