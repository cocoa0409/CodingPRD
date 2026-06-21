"""Validation precedence and cross-entity state guards: which error surfaces
when two conditions both hold (frozen vs insufficient stock; slot-not-on-machine
vs overfill), and the cross-entity gates (reconcile requires DISPATCHED route;
sale requires non-FROZEN machine).
"""
from test_helpers import validate_success, validate_error, api_client, counted_line
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_ticket,
)
from test_helpers.test_users import TEST_USERS, make_route_driver_headers

FIELD_OPS = TEST_USERS["field_ops_headers"]


# ─── priority_pair / ppvc_frozen_beats_insufficient_stock ──────────────────

def test_frozen_machine_outranks_insufficient_stock_on_sale():
    """PRD §3.6: "A sale on a FROZEN machine is refused with ERR_MACHINE_FROZEN.
    The referenced slot must belong to the target machine and be ACTIVE, or the
    sale is refused with ERR_SLOT_NOT_ON_MACHINE. The requested quantity must not
    exceed the slot's on_hand (the sum of remaining_units across the slot's
    AVAILABLE lots); if the FIFO walk runs short, the sale is refused with
    ERR_INSUFFICIENT_STOCK (HTTP 409)."

    A sale on a FROZEN machine whose slot also has on_hand 0 returns the
    frozen error, which PRD prose lists before the insufficient-stock check.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_beats_insufficient_stock
    """
    set_clock("2026-06-08T00:00:00Z")
    host = make_host(name="PP Host", contact_email="pp@x.com")
    prod = make_product(sku="PP1", name="PP Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-9", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="F1",
                     capacity=10, par_level=10, price_cents=100)
    # Blocking ticket freezes the machine; slot never stocked (on_hand 0).
    make_ticket(machine["id"], issue_type="VANDALISM", blocking=True)

    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 5, "payment_method": "CASHLESS"},
        FIELD_OPS)
    validate_error(res, "ERR_MACHINE_FROZEN", expected_status=409)


def test_frozen_sale_rejected_even_when_stocked():
    """PRD §3.6: "A sale on a FROZEN machine is refused with ERR_MACHINE_FROZEN."

    Confirms the frozen guard fires regardless of stock state (the safety check is
    not contingent on the fiscal stock check).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_frozen_beats_insufficient_stock
    """
    set_clock("2026-06-08T00:00:00Z")
    host = make_host(name="PP Host 2", contact_email="pp2@x.com")
    prod = make_product(sku="PP1b", name="PP Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-9b", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="F1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="PP Drv", employee_code="EMPpp")
    route = make_route(driver["id"], "2026-06-08T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    # Freeze AFTER stocking; slot has plenty of stock, only the frozen rule fails.
    make_ticket(machine["id"], issue_type="VANDALISM", blocking=True)

    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 1, "payment_method": "CASHLESS"},
        FIELD_OPS)
    validate_error(res, "ERR_MACHINE_FROZEN", expected_status=409)


# ─── priority_pair / ppvc_slot_not_on_machine_beats_overfill ───────────────

def test_slot_not_on_machine_outranks_overfill_on_reconcile():
    """PRD §3.5: "every slot_id named in counted_lines to belong to this visit's
    machine and to be ACTIVE, or it is rejected with ERR_SLOT_NOT_ON_MACHINE (HTTP
    409); and, for each line, the sum of its refill_units and its physical_count
    to be no greater than the slot's capacity, or it is rejected with
    ERR_SLOT_OVERFILL (HTTP 422)."

    A reconcile line whose slot belongs to a DIFFERENT machine AND overfills that
    slot returns the slot-not-on-machine error, which PRD prose lists before the
    overfill check.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_slot_not_on_machine_beats_overfill
    """
    set_clock("2026-06-04T00:00:00Z")
    host = make_host(name="PP2 Host", contact_email="pp2x@x.com")
    prod = make_product(sku="PP2", name="PP2 Item", category="SNACK", unit_cost_cents=30)
    machineA = make_machine(host["id"], asset_tag="M-A", machine_type="SNACK_VENDOR")
    slotA = make_slot(machineA["id"], prod["id"], slot_code="G1",
                      capacity=10, par_level=10, price_cents=100)
    machineB = make_machine(host["id"], asset_tag="M-B", machine_type="SNACK_VENDOR")
    slotB = make_slot(machineB["id"], prod["id"], slot_code="H1",
                      capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Mix", employee_code="EMP9")
    route = make_route(driver["id"], "2026-06-04T00:00:00Z")
    stop = make_stop(route["id"], machineA["id"])
    dispatch(route["id"])
    vA0 = machineA["version"]
    # Visit on machine-A's stop references machine-B's slot with refill 999 (> cap 10).
    visit = open_visit(stop["id"], [counted_line(slotB["id"], 0, 999)], vA0, driver["id"])

    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": vA0}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_SLOT_NOT_ON_MACHINE", expected_status=409)


def test_overfill_alone_returns_slot_overfill():
    """PRD §3.5: "for each line, the sum of its refill_units and its
    physical_count to be no greater than the slot's capacity, or it is rejected
    with ERR_SLOT_OVERFILL (HTTP 422)."

    With the slot correctly on the visit's machine, only the overfill rule fails,
    isolating the lower-priority error.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_slot_not_on_machine_beats_overfill
    """
    set_clock("2026-06-04T00:00:00Z")
    host = make_host(name="OF only", contact_email="ofonly@x.com")
    prod = make_product(sku="OFO", name="OFO Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-OF", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="G1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="OF Drv", employee_code="EMPof")
    route = make_route(driver["id"], "2026-06-04T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    # refill 5 + physical 8 = 13 > capacity 10.
    visit = open_visit(stop["id"], [counted_line(slot["id"], 8, 5)], v0, driver["id"])

    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": v0}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_SLOT_OVERFILL", expected_status=422)


# ─── cross_entity_state_dependency / cesd_reconcile_requires_route_dispatched ─

def test_reconcile_blocked_when_route_not_dispatched():
    """PRD §3.5: "reconcile requires: the parent route to be DISPATCHED, or it is
    rejected with ERR_ROUTE_NOT_DISPATCHED (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/cesd_reconcile_requires_route_dispatched
    """
    set_clock("2026-06-07T00:00:00Z")
    host = make_host(name="Dep Host", contact_email="dep@x.com")
    prod = make_product(sku="DEP", name="Dep Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-12", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="K1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Dep Drv", employee_code="EMP12")
    route = make_route(driver["id"], "2026-06-07T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    # Route is never dispatched. Open a DRAFT visit, then attempt reconcile.
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])

    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": v0}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_ROUTE_NOT_DISPATCHED", expected_status=409)


def test_reconcile_succeeds_once_route_dispatched():
    """PRD §3.5: "Reconciling a visit is a RouteDriver action that advances the
    visit DRAFT -> RECONCILED."
    PRD §3.5: "reconcile requires: the parent route to be DISPATCHED, or it is
    rejected with ERR_ROUTE_NOT_DISPATCHED (HTTP 409)".

    The same visit that fails while the route is DRAFT reconciles cleanly once the
    route is dispatched, isolating the route-state gate as the only difference.

    Design: Difficulty/cross_entity_state_dependency/cesd_reconcile_requires_route_dispatched
    """
    set_clock("2026-06-07T00:00:00Z")
    host = make_host(name="Dep Host 2", contact_email="dep2@x.com")
    prod = make_product(sku="DEP2", name="Dep Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-12b", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="K1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Dep Drv2", employee_code="EMP12b")
    route = make_route(driver["id"], "2026-06-07T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": v0}, make_route_driver_headers(driver["id"]))
    reconciled = validate_success(res, 200)
    assert reconciled["status"] == "RECONCILED", reconciled


# ─── cross_entity_state_dependency / cesd_sale_requires_machine_not_frozen ─

def test_sale_blocked_on_frozen_machine_despite_stock():
    """PRD §3.6: "A sale on a FROZEN machine is refused with ERR_MACHINE_FROZEN."
    PRD §3.2: "When a ServiceTicket marked as blocking enters an open state, the
    machine transitions IN_SERVICE -> FROZEN."

    Design: Difficulty/cross_entity_state_dependency/cesd_sale_requires_machine_not_frozen
    """
    set_clock("2026-06-08T00:00:00Z")
    host = make_host(name="Frz Host", contact_email="frz@x.com")
    prod = make_product(sku="FRZ", name="Frz Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-13", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="L1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Frz Drv", employee_code="EMP13")
    route = make_route(driver["id"], "2026-06-08T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    # Freeze with a blocking COIN_MECH ticket; slot still has on_hand 10.
    make_ticket(machine["id"], issue_type="COIN_MECH", blocking=True)

    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 1, "payment_method": "CASHLESS"},
        FIELD_OPS)
    validate_error(res, "ERR_MACHINE_FROZEN", expected_status=409)


def test_blocking_ticket_freezes_machine_service_status():
    """PRD §3.2: "When a ServiceTicket marked as blocking enters an open state,
    the machine transitions IN_SERVICE -> FROZEN."
    PRD §3.8: "a machine is FROZEN whenever at least one of its tickets has
    blocking true and a status of OPEN, IN_PROGRESS, or REOPENED".

    Design: Difficulty/cross_entity_state_dependency/cesd_sale_requires_machine_not_frozen
    """
    set_clock("2026-06-08T00:00:00Z")
    host = make_host(name="Frz Host 2", contact_email="frz2@x.com")
    machine = make_machine(host["id"], asset_tag="M-13b", machine_type="SNACK_VENDOR")
    before = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert before["service_status"] == "IN_SERVICE", before
    make_ticket(machine["id"], issue_type="COIN_MECH", blocking=True)
    after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after["service_status"] == "FROZEN", after
