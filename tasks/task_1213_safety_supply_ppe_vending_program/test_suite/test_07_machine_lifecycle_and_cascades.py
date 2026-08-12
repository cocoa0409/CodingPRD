"""VendingMachine cycles, service-ticket cascades, restock cascades (PRD §3.3, §3.5, §3.6)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    AUDITOR,
    FINANCE,
    TECH,
    create_restock_order_payload,
    create_service_ticket_payload,
    open_audit,
    open_batch,
    reverse_ok,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine,
    setup_machine_with_slot,
    setup_manager,
    setup_slot_for_machine,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / vending_machine_offline_service_cycles
# ---------------------------------------------------------------------------


def test_machine_offline_toggle_cycle(api):
    """PRD §3.3: "From `ACTIVE` a technician may take the machine `OFFLINE`
    and later restore it to `ACTIVE`."
    PRD §3.3: "Every successful lifecycle write increments the machine's
    `version`."

    Design: Difficulty/non_linear_state_machine/vending_machine_offline_service_cycles
    """
    item = setup_item(sku="CYC-M1", base_list_price_cents=700)
    machine, _slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0)
    assert machine["status"] == "ACTIVE"
    v_active = machine["version"]

    off = validate_success(
        api.update_machine(machine["id"], {"status": "OFFLINE"}, TECH), 200
    )
    assert off["status"] == "OFFLINE"
    assert off["version"] > v_active

    back = validate_success(
        api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH), 200
    )
    assert back["status"] == "ACTIVE"
    assert back["version"] > off["version"]


def test_machine_service_cycle_via_ticket(api):
    """PRD §3.6: "On start the ticket moves to `IN_PROGRESS`, the machine
    moves from `ACTIVE` or `OFFLINE` into `IN_SERVICE`, and every restock
    order of that machine in `SUGGESTED` or `PICKED` is cancelled."
    PRD §3.6: "Resolution moves the ticket from `IN_PROGRESS` to `RESOLVED`,
    returns the machine from `IN_SERVICE` to `ACTIVE`, and runs the
    post-service restock sweep".

    Design: Difficulty/non_linear_state_machine/vending_machine_offline_service_cycles
    """
    item = setup_item(sku="CYC-M1", base_list_price_cents=700)
    machine, _slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0)
    ticket = get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="PREVENTIVE",
                window_start="2026-05-01T00:00:00Z",
                window_end="2026-05-02T00:00:00Z",
            ),
            TECH,
        )
    )
    get_success_data(api.start_service_ticket(ticket["id"], TECH))
    m = get_success_data(api.get_machine(machine["id"], ANY))
    assert m["status"] == "IN_SERVICE"

    resolved = validate_success(api.resolve_service_ticket(ticket["id"], TECH), 200)
    assert resolved["status"] == "RESOLVED"
    m = get_success_data(api.get_machine(machine["id"], ANY))
    assert m["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / reversal_triggers_restock_autocancel_chain
# ---------------------------------------------------------------------------


def _setup_reversal_autocancel(api):
    """Machine ACTIVE slot cap 20 par 5 stocked to 6; vend qty 2 -> on_hand 4
    <= par 5 -> AUTO_PAR RestockOrder SUGGESTED qty 16 (capacity - on_hand)."""
    sc = setup_vend_scenario(sku="CASC-R", base_price=300, period_limit_qty=50,
                             period_window_days=30, capacity=20, par_level=5,
                             initial_stock=6, with_manager=True)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
                  idempotency_key="rc-1")
    auto_orders = get_success_data(
        api.list_restock_orders(
            ANY, params={"slot_id": sc["slot"]["id"], "status": "SUGGESTED"}
        )
    )
    assert len(auto_orders) == 1, "AUTO_PAR trigger created exactly one order"
    sc["issuance"] = iss
    sc["auto_order"] = auto_orders[0]
    return sc


def test_reversal_restores_on_hand(api):
    """PRD §3.5: "The slot's `on_hand_qty` rises by the vended `qty` — one
    unit for a serialized line".

    Design: Difficulty/transitive_cascade/reversal_triggers_restock_autocancel_chain
    """
    sc = _setup_reversal_autocancel(api)
    assert sc["auto_order"]["qty"] == 16, "naive fill: capacity 20 - on_hand 4"
    assert sc["auto_order"]["source"] == "AUTO_PAR"
    assert sc["auto_order"]["status"] == "SUGGESTED"

    rev = reverse_ok(sc["manager_headers"], sc["issuance"]["id"])
    assert rev["status"] == "REVERSED"

    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 6


def test_reversal_autocancels_suggested_restock(api):
    """PRD §3.5: "if that restoration pushes the slot strictly above
    `par_level` while a restock order for the slot sits in `SUGGESTED`, the
    now-unneeded order is cancelled."

    Design: Difficulty/transitive_cascade/reversal_triggers_restock_autocancel_chain
    """
    sc = _setup_reversal_autocancel(api)
    reverse_ok(sc["manager_headers"], sc["issuance"]["id"])
    auto_now = get_success_data(api.get_restock_order(sc["auto_order"]["id"], ANY))
    assert auto_now["status"] == "CANCELLED", (
        "restored on_hand 6 > par 5 -> SUGGESTED order auto-cancelled"
    )


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / service_start_cancels_open_restocks_chain
# ---------------------------------------------------------------------------


def _setup_service_cascade(api):
    """Machine ACTIVE slot cap 20 par 5 stocked to 4 (below par). One open
    SUGGESTED manual order qty 10. Ticket window covering default clock."""
    item = setup_item(sku="CASC-S", base_list_price_cents=300)
    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=5)
    stock_slot(machine, slot, 4)
    open_order = get_success_data(
        api.create_restock_order(
            create_restock_order_payload(machine_id=machine["id"],
                                         slot_id=slot["id"], qty=10),
            TECH,
        )
    )
    ticket = get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="JAM",
                window_start="2026-05-01T00:00:00Z",
                window_end="2026-05-02T00:00:00Z",
            ),
            TECH,
        )
    )
    return {"item": item, "machine": machine, "slot": slot,
            "open_order": open_order, "ticket": ticket}


def test_service_start_cascades_to_machine_and_restocks(api):
    """PRD §3.6: "On start the ticket moves to `IN_PROGRESS`, the machine
    moves from `ACTIVE` or `OFFLINE` into `IN_SERVICE`, and every restock
    order of that machine in `SUGGESTED` or `PICKED` is cancelled."

    Design: Difficulty/transitive_cascade/service_start_cancels_open_restocks_chain
    """
    fx = _setup_service_cascade(api)
    started = validate_success(api.start_service_ticket(fx["ticket"]["id"], TECH), 200)
    assert started["status"] == "IN_PROGRESS"
    m = get_success_data(api.get_machine(fx["machine"]["id"], ANY))
    assert m["status"] == "IN_SERVICE"
    ro = get_success_data(api.get_restock_order(fx["open_order"]["id"], ANY))
    assert ro["status"] == "CANCELLED"


def test_service_resolve_triggers_par_restock_sweep(api):
    """PRD §3.6: "Resolution moves the ticket from `IN_PROGRESS` to
    `RESOLVED`, returns the machine from `IN_SERVICE` to `ACTIVE`, and runs
    the post-service restock sweep: for every slot of the machine whose
    item is non-serialized, whose `on_hand_qty` is at or below `par_level`,
    and which has no order in `SUGGESTED` or `PICKED`, an `AUTO_PAR` order
    is auto-created with `qty` equal to `capacity` minus `on_hand_qty`."

    Design: Difficulty/transitive_cascade/service_start_cancels_open_restocks_chain
    """
    fx = _setup_service_cascade(api)
    get_success_data(api.start_service_ticket(fx["ticket"]["id"], TECH))
    get_success_data(api.resolve_service_ticket(fx["ticket"]["id"], TECH))
    m = get_success_data(api.get_machine(fx["machine"]["id"], ANY))
    assert m["status"] == "ACTIVE"

    auto_orders = get_success_data(
        api.list_restock_orders(
            ANY, params={"slot_id": fx["slot"]["id"], "status": "SUGGESTED"}
        )
    )
    assert len(auto_orders) == 1, "post-service sweep created one AUTO_PAR order"
    assert auto_orders[0]["qty"] == 16, "capacity 20 - on_hand 4"
    assert auto_orders[0]["source"] == "AUTO_PAR"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / vend_blocked_when_machine_offline
# ---------------------------------------------------------------------------


def test_vend_blocked_when_machine_offline(api):
    """PRD §3.4: "the machine must be `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/vend_blocked_when_machine_offline
    """
    sc = setup_vend_scenario(sku="XDEP-M", base_price=300, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    get_success_data(
        api.update_machine(sc["machine"]["id"], {"status": "OFFLINE"}, TECH)
    )
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="xm-1")
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ACTIVE)


def test_vend_succeeds_after_machine_restored(api):
    """PRD §3.4: "the machine must be `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`)".
    PRD §3.3: "From `ACTIVE` a technician may take the machine `OFFLINE`
    and later restore it to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/vend_blocked_when_machine_offline
    """
    sc = setup_vend_scenario(sku="XDEP-M", base_price=300, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    get_success_data(
        api.update_machine(sc["machine"]["id"], {"status": "OFFLINE"}, TECH)
    )
    validate_error(
        vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
             idempotency_key="xm-1"),
        ApiErrorId.ERR_MACHINE_NOT_ACTIVE,
    )
    get_success_data(
        api.update_machine(sc["machine"]["id"], {"status": "ACTIVE"}, TECH)
    )
    ok = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                 idempotency_key="xm-2")
    assert ok["qty"] == 1
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 9


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / audit_fieldwork_blocked_by_open_batch
# ---------------------------------------------------------------------------


def _setup_audit_blocked_by_open_batch(api):
    sc = setup_vend_scenario(sku="XDEP-A", base_price=300, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=5)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="xa-1")
    batch = open_batch(sc["cost_center"]["id"])
    audit = open_audit(scope="OVERRIDE_USAGE")
    sc["batch"] = batch
    sc["audit"] = audit
    return sc


def test_audit_fieldwork_blocked_while_open_batch_overlaps(api):
    """PRD §3.8: "Beginning fieldwork moves `DRAFT` to `FIELDWORK` and is
    refused while any chargeback batch whose period overlaps the audit's
    closed interval — closed-interval overlap on both sides — remains
    `OPEN` (`ERR_OPEN_BATCHES_EXIST`)."

    Design: Difficulty/cross_entity_state_dependency/audit_fieldwork_blocked_by_open_batch
    """
    sc = _setup_audit_blocked_by_open_batch(api)
    resp = api.begin_audit_fieldwork(sc["audit"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_OPEN_BATCHES_EXIST)
    a = get_success_data(api.get_compliance_audit(sc["audit"]["id"], ANY))
    assert a["status"] == "DRAFT"


def test_audit_fieldwork_unlocked_after_batch_close(api):
    """PRD §3.8: "Beginning fieldwork moves `DRAFT` to `FIELDWORK` and is
    refused while any chargeback batch whose period overlaps the audit's
    closed interval — closed-interval overlap on both sides — remains
    `OPEN` (`ERR_OPEN_BATCHES_EXIST`)."

    Design: Difficulty/cross_entity_state_dependency/audit_fieldwork_blocked_by_open_batch
    """
    sc = _setup_audit_blocked_by_open_batch(api)
    validate_error(
        api.begin_audit_fieldwork(sc["audit"]["id"], AUDITOR),
        ApiErrorId.ERR_OPEN_BATCHES_EXIST,
    )
    closed = validate_success(
        api.close_chargeback_batch(sc["batch"]["id"], FINANCE), 200
    )
    assert closed["line_count"] == 1
    ok = validate_success(api.begin_audit_fieldwork(sc["audit"]["id"], AUDITOR), 200)
    assert ok["status"] == "FIELDWORK"
