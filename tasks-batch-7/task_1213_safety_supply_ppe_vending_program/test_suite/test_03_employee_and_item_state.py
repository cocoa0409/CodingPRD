"""Employee + Item + Machine + Restock + Ticket + Batch + Audit state machines
(PRD §3.2, §3.3, §3.6, §3.7, §3.8)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    AUDITOR,
    FINANCE,
    TECH,
    create_chargeback_batch_payload,
    create_compliance_audit_payload,
    create_employee_payload,
    create_issuance_policy_payload,
    create_item_payload,
    create_job_role_payload,
    create_machine_payload,
    create_manager_override_payload,
    create_restock_order_payload,
    create_service_ticket_payload,
    create_slot_payload,
    grant_override,
    open_audit,
    open_batch,
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
    make_employee_headers,
    make_manager_headers,
)


def test_employee_suspend_reactivate_and_terminal_lockdown(api):
    """PRD §3.2: "Suspension moves `ACTIVE` to `SUSPENDED`, reinstatement
    moves `SUSPENDED` back to `ACTIVE`, and termination is allowed from
    either `ACTIVE` or `SUSPENDED`, landing in the terminal `TERMINATED`
    state. A status change from any other configuration is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.4: "the employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`)".

    Design: Corner/state_machines/employee_suspend_reactivate_and_terminal_lockdown
    """
    sc = setup_vend_scenario(sku="SM-E", period_limit_qty=10, period_window_days=30,
                             initial_stock=10)
    emp = sc["employee"]

    r1 = api.update_employee(emp["id"], {"status": "SUSPENDED"}, ADMIN)
    assert validate_success(r1, 200)["status"] == "SUSPENDED"

    # Vend while suspended.
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="sm-1")
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)

    r2 = api.update_employee(emp["id"], {"status": "ACTIVE"}, ADMIN)
    assert validate_success(r2, 200)["status"] == "ACTIVE"

    r3 = api.update_employee(emp["id"], {"status": "TERMINATED"}, ADMIN)
    assert validate_success(r3, 200)["status"] == "TERMINATED"

    r4 = api.update_employee(emp["id"], {"status": "ACTIVE"}, ADMIN)
    validate_error(r4, ApiErrorId.ERR_INVALID_STATE)


def test_item_discontinue_is_terminal(api):
    """PRD §3.1: "Discontinuation is a one-way door. An `EHSAdministrator`
    discontinues an `ACTIVE` item, moving it to `DISCONTINUED`; repeating the
    action against an item no longer `ACTIVE` is rejected with
    `ERR_ITEM_DISCONTINUED`. Once discontinued, the item refuses four
    operations with `ERR_ITEM_DISCONTINUED`: new vends, new planogram slots,
    new restock orders for slots holding it, and new serialized-unit
    registrations."

    Design: Corner/state_machines/item_discontinue_is_terminal
    """
    sc = setup_vend_scenario(sku="SM-DI", period_limit_qty=10, period_window_days=30,
                             initial_stock=5)
    item = sc["item"]

    d1 = api.discontinue_item(item["id"], ADMIN)
    assert validate_success(d1, 200)["status"] == "DISCONTINUED"

    d2 = api.discontinue_item(item["id"], ADMIN)
    validate_error(d2, ApiErrorId.ERR_ITEM_DISCONTINUED)

    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="di-1")
    validate_error(resp, ApiErrorId.ERR_ITEM_DISCONTINUED)


def test_machine_commission_requires_planogram(api):
    """PRD §3.3: "Commissioning completes — `COMMISSIONING` to `ACTIVE` —
    only once the machine has at least one planogram slot, failing with
    `ERR_MACHINE_NO_PLANOGRAM` otherwise."

    Design: Corner/state_machines/machine_commission_requires_planogram
    """
    item = setup_item(sku="SM-CM", base_list_price_cents=100)
    machine = setup_machine(location_code="LOC-SM3", site_name="P7", model="VM-1")

    r1 = api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH)
    validate_error(r1, ApiErrorId.ERR_MACHINE_NO_PLANOGRAM)

    setup_slot_for_machine(machine, item_id=item["id"], capacity=10, par_level=0,
                           slot_code="A1")

    r2 = api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH)
    assert validate_success(r2, 200)["status"] == "ACTIVE"


def test_restock_pick_twice_rejected(api):
    """PRD §3.6: "any pick, load, or cancel attempted from a disallowed state
    fails with `ERR_RESTOCK_ORDER_INVALID_STATE`."

    Design: Corner/state_machines/restock_pick_twice_rejected
    """
    item = setup_item(sku="SM-RP", base_list_price_cents=100)
    machine, slot = setup_machine_with_slot(item["id"], capacity=30, par_level=2)
    order = get_success_data(
        api.create_restock_order(
            create_restock_order_payload(machine_id=machine["id"], slot_id=slot["id"],
                                         qty=5),
            TECH,
        )
    )
    p1 = api.pick_restock_order(order["id"], TECH)
    assert validate_success(p1, 200)["status"] == "PICKED"
    p2 = api.pick_restock_order(order["id"], TECH)
    validate_error(p2, ApiErrorId.ERR_RESTOCK_ORDER_INVALID_STATE)


def test_service_ticket_resolve_from_open_rejected(api):
    """PRD §3.6: "Resolution moves the ticket from `IN_PROGRESS` to
    `RESOLVED`". §3.8: "Each of these three transitions attempted from the
    wrong state fails with `ERR_AUDIT_INVALID_STATE`." (ticket analogue from
    §3.6: "Starting service is the consequential transition: the ticket must
    be `OPEN` (else `ERR_SERVICE_TICKET_INVALID_STATE`)".)

    Design: Corner/state_machines/service_ticket_resolve_from_open_rejected
    """
    machine = setup_machine(location_code="LOC-SM5", site_name="P9", model="VM-1")
    ticket = get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="JAM",
                window_start="2026-05-10T08:00:00Z",
                window_end="2026-05-10T12:00:00Z",
            ),
            TECH,
        )
    )
    r = api.resolve_service_ticket(ticket["id"], TECH)
    validate_error(r, ApiErrorId.ERR_SERVICE_TICKET_INVALID_STATE)
    now = get_success_data(api.get_service_ticket(ticket["id"], ANY))
    assert now["status"] == "OPEN"


def test_chargeback_settle_from_open_rejected(api):
    """PRD §3.7: "Any close, dispute, or settle attempted from the wrong
    state fails with `ERR_BATCH_INVALID_STATE`."

    Design: Corner/state_machines/chargeback_settle_from_open_rejected
    """
    cc = setup_cost_center(code="CC-SM6", name="Ops")
    batch = open_batch(cc["id"])
    r = api.settle_chargeback_batch(batch["id"], FINANCE)
    validate_error(r, ApiErrorId.ERR_BATCH_INVALID_STATE)
    now = get_success_data(api.get_chargeback_batch(batch["id"], ANY))
    assert now["status"] == "OPEN"


def test_audit_close_from_fieldwork_rejected(api):
    """PRD §3.8: "Filing findings moves `FIELDWORK` to `FINDINGS_FILED` and
    computes the findings; closing moves `FINDINGS_FILED` to the terminal
    `CLOSED`. Each of these three transitions attempted from the wrong state
    fails with `ERR_AUDIT_INVALID_STATE`."

    Design: Corner/state_machines/audit_close_from_fieldwork_rejected
    """
    sc = setup_vend_scenario(sku="SM-AU", period_limit_qty=10, period_window_days=30,
                             initial_stock=5)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="au-1")
    batch = open_batch(sc["cost_center"]["id"])
    get_success_data(api.close_chargeback_batch(batch["id"], FINANCE))

    audit = open_audit(scope="OVERRIDE_USAGE")
    get_success_data(api.begin_audit_fieldwork(audit["id"], AUDITOR))

    r = api.close_audit(audit["id"], AUDITOR)
    validate_error(r, ApiErrorId.ERR_AUDIT_INVALID_STATE)
    now = get_success_data(api.get_compliance_audit(audit["id"], ANY))
    assert now["status"] == "FIELDWORK"


def test_override_revoke_twice_rejected(api):
    """PRD §3.5: "revoking works only from `ACTIVE` (otherwise
    `ERR_OVERRIDE_NOT_ACTIVE`)".

    Design: Corner/state_machines/override_revoke_twice_rejected
    """
    cc = setup_cost_center(code="CC-SM8", name="Ops")
    role = setup_job_role(role_name="TECH-OR")
    item = setup_item(sku="SM-OR", base_list_price_cents=100)
    emp, _ = setup_employee(role["id"], cc["id"], employee_code="E-SM8",
                            full_name="Tech OR")
    mgr, mgr_headers = setup_manager(role["id"], cc["id"], employee_code="M-SM8",
                                     full_name="Mgr OR")
    ov = grant_override(mgr_headers, employee_id=emp["id"], item_id=item["id"],
                        approved_qty=2, valid_from="2026-05-01",
                        valid_until="2026-05-31", reason_code="OTHER")

    r1 = api.revoke_manager_override(ov["id"], mgr_headers)
    assert validate_success(r1, 200)["status"] == "REVOKED"
    r2 = api.revoke_manager_override(ov["id"], mgr_headers)
    validate_error(r2, ApiErrorId.ERR_OVERRIDE_NOT_ACTIVE)


def test_issuance_double_reverse_rejected(api):
    """PRD §3.5: "A `Manager` reverses an issuance currently in `POSTED` —
    any other state fails with `ERR_ISSUANCE_ALREADY_REVERSED`".

    Design: Corner/state_machines/issuance_double_reverse_rejected
    """
    sc = setup_vend_scenario(sku="SM-IR", period_limit_qty=10, period_window_days=30,
                             initial_stock=5, with_manager=True)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                  idempotency_key="ir-1")
    r1 = api.reverse_issuance(iss["id"], sc["manager_headers"])
    assert validate_success(r1, 200)["status"] == "REVERSED"
    r2 = api.reverse_issuance(iss["id"], sc["manager_headers"])
    validate_error(r2, ApiErrorId.ERR_ISSUANCE_ALREADY_REVERSED)
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 5


def test_machine_decommission_blocked_by_open_restock(api):
    """PRD §3.3: "Decommissioning is allowed from `ACTIVE` or `OFFLINE`, but
    only when the machine has no restock orders in `SUGGESTED` or `PICKED`
    (else `ERR_OPEN_RESTOCK_ORDERS_EXIST`) and no service tickets in `OPEN`
    or `IN_PROGRESS` (else `ERR_OPEN_SERVICE_TICKETS_EXIST`)".

    Design: Corner/state_machines/machine_decommission_blocked_by_open_restock
    """
    item = setup_item(sku="SM-DC", base_list_price_cents=100)
    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0)
    stock_slot(machine, slot, 3)
    open_order = get_success_data(
        api.create_restock_order(
            create_restock_order_payload(machine_id=machine["id"], slot_id=slot["id"],
                                         qty=2),
            TECH,
        )
    )

    r1 = api.update_machine(machine["id"], {"status": "DECOMMISSIONED"}, TECH)
    validate_error(r1, ApiErrorId.ERR_OPEN_RESTOCK_ORDERS_EXIST)

    get_success_data(api.cancel_restock_order(open_order["id"], TECH))
    r2 = api.update_machine(machine["id"], {"status": "DECOMMISSIONED"}, TECH)
    assert validate_success(r2, 200)["status"] == "DECOMMISSIONED"


def test_employee_termination_cascades_override_revoke(api):
    """PRD §3.2: "Termination is the consequential transition: every `ACTIVE`
    manager override belonging to the employee is cascaded to `REVOKED`,
    with its consumed quantity preserved for audit."

    Design: Corner/state_machines/employee_termination_cascades_override_revoke
    """
    cc = setup_cost_center(code="CC-SM11", name="Ops")
    role = setup_job_role(role_name="TECH-TC")
    item = setup_item(sku="SM-TC", base_list_price_cents=100)
    emp, _ = setup_employee(role["id"], cc["id"], employee_code="E-SM11",
                            full_name="Tech TC")
    mgr, mgr_headers = setup_manager(role["id"], cc["id"], employee_code="M-SM11",
                                     full_name="Mgr TC")
    ov = grant_override(mgr_headers, employee_id=emp["id"], item_id=item["id"],
                        approved_qty=4, valid_from="2026-05-01",
                        valid_until="2026-05-31", reason_code="PROJECT")

    r = api.update_employee(emp["id"], {"status": "TERMINATED"}, ADMIN)
    assert validate_success(r, 200)["status"] == "TERMINATED"

    ov_now = get_success_data(api.get_manager_override(ov["id"], ANY))
    assert ov_now["status"] == "REVOKED"
    assert ov_now["consumed_qty"] == 0
