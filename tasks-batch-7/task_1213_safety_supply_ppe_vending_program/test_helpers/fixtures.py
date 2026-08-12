"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chargeback_batch_payload,
    create_compliance_audit_payload,
    create_contract_price_payload,
    create_cost_center_payload,
    create_employee_payload,
    create_issuance_payload,
    create_issuance_policy_payload,
    create_item_payload,
    create_job_role_payload,
    create_machine_payload,
    create_manager_override_payload,
    create_restock_order_payload,
    create_serialized_unit_payload,
    create_service_ticket_payload,
    create_slot_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_manager_headers,
)

ADMIN = TEST_USERS["ehs_admin_headers"]
TECH = TEST_USERS["vending_tech_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Catalog / personnel primitives
# ---------------------------------------------------------------------------


def setup_cost_center(code="CC-0001", name="Ops"):
    return get_success_data(
        api_client.create_cost_center(
            create_cost_center_payload(cost_center_code=code, name=name), FINANCE
        )
    )


def setup_job_role(role_name="ROLE-1"):
    return get_success_data(
        api_client.create_job_role(create_job_role_payload(role_name=role_name), ADMIN)
    )


def setup_item(**overrides):
    return get_success_data(
        api_client.create_item(create_item_payload(**overrides), ADMIN)
    )


def setup_employee(role_id, cost_center_id, **overrides):
    """Create an employee under role + cost center. Returns (employee_dict,
    headers_for_employee_role)."""
    emp = get_success_data(
        api_client.create_employee(
            create_employee_payload(
                job_role_id=role_id, home_cost_center_id=cost_center_id, **overrides
            ),
            ADMIN,
        )
    )
    return emp, make_employee_headers(emp["id"])


def setup_manager(role_id, cost_center_id, **overrides):
    """Create a manager (Employee with is_manager=True). Returns (employee_dict,
    headers_for_manager_role)."""
    overrides.setdefault("is_manager", True)
    mgr = get_success_data(
        api_client.create_employee(
            create_employee_payload(
                job_role_id=role_id, home_cost_center_id=cost_center_id, **overrides
            ),
            ADMIN,
        )
    )
    return mgr, make_manager_headers(mgr["id"])


# ---------------------------------------------------------------------------
# Tier 2: Machine + slot
# ---------------------------------------------------------------------------


def setup_machine(**overrides):
    """Create a machine in COMMISSIONING; returns (machine_dict, version_at_create)."""
    machine = get_success_data(
        api_client.create_machine(create_machine_payload(**overrides), TECH)
    )
    return machine


def setup_slot_for_machine(machine, item_id, capacity=20, par_level=0, slot_code=None):
    """Create one slot against a machine, reading fresh machine version first."""
    current = get_success_data(api_client.get_machine(machine["id"], ANY))
    payload = create_slot_payload(
        item_id=item_id, capacity=capacity, par_level=par_level,
        expected_machine_version=current["version"],
    )
    if slot_code is not None:
        payload["slot_code"] = slot_code
    slot = get_success_data(api_client.create_slot(machine["id"], payload, TECH))
    return slot


def activate_machine(machine_id):
    return get_success_data(
        api_client.update_machine(machine_id, {"status": "ACTIVE"}, TECH)
    )


def setup_machine_with_slot(item_id, capacity=20, par_level=0, slot_code="A1",
                            activate=True, **machine_overrides):
    """Create machine + one slot, optionally commission to ACTIVE.
    Returns (machine_after_activation, slot)."""
    machine = setup_machine(**machine_overrides)
    slot = setup_slot_for_machine(
        machine, item_id=item_id, capacity=capacity, par_level=par_level,
        slot_code=slot_code,
    )
    if activate:
        machine = activate_machine(machine["id"])
    return machine, slot


# ---------------------------------------------------------------------------
# Tier 3: Stock loading (restock to a target on_hand)
# ---------------------------------------------------------------------------


def stock_slot(machine, slot, qty):
    """Manually create a restock order, pick, load. Machine must be ACTIVE/OFFLINE.
    Returns the LOADED order."""
    order = get_success_data(
        api_client.create_restock_order(
            create_restock_order_payload(
                machine_id=machine["id"], slot_id=slot["id"], qty=qty
            ),
            TECH,
        )
    )
    get_success_data(api_client.pick_restock_order(order["id"], TECH))
    order = get_success_data(api_client.load_restock_order(order["id"], TECH))
    return order


# ---------------------------------------------------------------------------
# Tier 4: Vend-capable GENERAL-item scenario
# ---------------------------------------------------------------------------


def setup_vend_scenario(
    sku=None,
    base_price=100,
    period_limit_qty=10,
    period_window_days=30,
    capacity=20,
    par_level=0,
    initial_stock=10,
    contract_tiers=None,
    item_category="GENERAL",
    item_extra=None,
    with_manager=False,
    employee_overrides=None,
):
    """Build a full vend-capable scenario:
    cost center + role + item (+ optional contract tiers) + policy + employee
    (+ optional manager) + ACTIVE machine + slot stocked to initial_stock.

    Returns a dict with keys:
      cost_center, job_role, item, policy, employee, employee_headers,
      manager (opt), manager_headers (opt), machine, slot, initial_orders.
    """
    item_overrides = {"category": item_category, "base_list_price_cents": base_price}
    if sku is not None:
        item_overrides["sku"] = sku
    if item_extra:
        item_overrides.update(item_extra)
    item = setup_item(**item_overrides)
    cc = setup_cost_center()
    role = setup_job_role()
    policy = get_success_data(
        api_client.create_issuance_policy(
            create_issuance_policy_payload(
                job_role_id=role["id"],
                item_id=item["id"],
                period_limit_qty=period_limit_qty,
                period_window_days=period_window_days,
            ),
            ADMIN,
        )
    )
    emp, emp_headers = setup_employee(role["id"], cc["id"], **(employee_overrides or {}))
    machine, slot = setup_machine_with_slot(
        item["id"], capacity=capacity, par_level=par_level
    )
    initial_orders = []
    if initial_stock > 0:
        initial_orders.append(stock_slot(machine, slot, initial_stock))
    out = {
        "cost_center": cc,
        "job_role": role,
        "item": item,
        "policy": policy,
        "employee": emp,
        "employee_headers": emp_headers,
        "machine": machine,
        "slot": slot,
        "initial_orders": initial_orders,
    }
    if contract_tiers:
        for t in contract_tiers:
            get_success_data(
                api_client.create_contract_price(
                    create_contract_price_payload(item_id=item["id"], **t), ADMIN
                )
            )
    if with_manager:
        mgr, mgr_headers = setup_manager(role["id"], cc["id"])
        out["manager"] = mgr
        out["manager_headers"] = mgr_headers
    return out


# ---------------------------------------------------------------------------
# Tier 5: Vend + reverse helpers
# ---------------------------------------------------------------------------


def vend(employee_headers, machine, slot, qty, idempotency_key, serialized_unit_id=None,
         manager_override_id=None):
    payload = create_issuance_payload(
        machine_id=machine["id"],
        slot_id=slot["id"],
        qty=qty,
        idempotency_key=idempotency_key,
    )
    if serialized_unit_id is not None:
        payload["serialized_unit_id"] = serialized_unit_id
    if manager_override_id is not None:
        payload["manager_override_id"] = manager_override_id
    return api_client.create_issuance(payload, employee_headers)


def vend_ok(employee_headers, machine, slot, qty, idempotency_key, **kw):
    """Vend and assert success; returns the IssuanceTransaction data."""
    return get_success_data(
        vend(employee_headers, machine, slot, qty, idempotency_key, **kw)
    )


def reverse_ok(manager_headers, issuance_id):
    return get_success_data(api_client.reverse_issuance(issuance_id, manager_headers))


# ---------------------------------------------------------------------------
# Tier 6: Override helper
# ---------------------------------------------------------------------------


def grant_override(manager_headers, employee_id, item_id, approved_qty=2,
                   valid_from="2026-05-01", valid_until="2026-05-31",
                   reason_code="PROJECT"):
    return get_success_data(
        api_client.create_manager_override(
            create_manager_override_payload(
                employee_id=employee_id,
                item_id=item_id,
                approved_qty=approved_qty,
                valid_from=valid_from,
                valid_until=valid_until,
                reason_code=reason_code,
            ),
            manager_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 7: Clock helper
# ---------------------------------------------------------------------------


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 8: Chargeback batch helper
# ---------------------------------------------------------------------------


def open_batch(cost_center_id, period_start="2026-05-01", period_end="2026-06-01"):
    return get_success_data(
        api_client.create_chargeback_batch(
            create_chargeback_batch_payload(
                cost_center_id=cost_center_id,
                period_start=period_start,
                period_end=period_end,
            ),
            FINANCE,
        )
    )


# ---------------------------------------------------------------------------
# Tier 9: Compliance audit helper
# ---------------------------------------------------------------------------


def open_audit(scope="OVERRIDE_USAGE", period_start="2026-05-01", period_end="2026-05-31"):
    return get_success_data(
        api_client.create_compliance_audit(
            create_compliance_audit_payload(
                scope=scope, period_start=period_start, period_end=period_end
            ),
            AUDITOR,
        )
    )


# ---------------------------------------------------------------------------
# Tier 10: Serialized unit helpers
# ---------------------------------------------------------------------------


def register_serialized_unit(item_id, slot_id, serial_number=None):
    payload = create_serialized_unit_payload(item_id=item_id, slot_id=slot_id)
    if serial_number is not None:
        payload["serial_number"] = serial_number
    return get_success_data(api_client.create_serialized_unit(payload, ADMIN))
