"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every helper builds its preconditions from scratch against PRD-declared
endpoints, using get_success_data() so setup failures surface as clear
"Setup step failed" errors. Identity threading: Manager/Employee role calls
always go through make_manager_headers / make_employee_headers with the actual
Employee.id of the acting user.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_abuse_flag_payload,
    create_budget_payload,
    create_catalog_item_payload,
    create_department_payload,
    create_employee_payload,
    create_nomination_payload,
    create_program_payload,
    create_redemption_order_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_employee_headers, make_manager_headers

HR = TEST_USERS["hr_admin_headers"]
FIN = TEST_USERS["finance_admin_headers"]
PAY = TEST_USERS["payroll_specialist_headers"]
VOPS = TEST_USERS["vendor_ops_headers"]

DEFAULT_WINDOW_START = TEST_DEFAULTS["BUDGET_WINDOW_START"]      # 2026-01-01
DEFAULT_WINDOW_END = TEST_DEFAULTS["BUDGET_WINDOW_END"]          # 2027-01-01
DEFAULT_ITEM_WINDOW_START = TEST_DEFAULTS["ITEM_WINDOW_START"]   # 2026-01-01T00:00:00Z
DEFAULT_ITEM_WINDOW_END = TEST_DEFAULTS["ITEM_WINDOW_END"]       # 2027-01-01T00:00:00Z


# ─── Tier 1: single-entity state progression ────────────────────────────────

def create_program(**overrides) -> dict:
    """Create a program (lands in DRAFT). Returns the program."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), HR))


def create_and_activate_program(**overrides) -> dict:
    """Create program + activate. Returns the ACTIVE program."""
    program = create_program(**overrides)
    return get_success_data(api_client.activate_program(program["id"], HR))


def create_department(name="Eng", chargeback_account_code="GL-ENG") -> dict:
    return get_success_data(api_client.create_department(
        create_department_payload(name=name, chargeback_account_code=chargeback_account_code), HR
    ))


def create_employee(department_id, **overrides) -> dict:
    return get_success_data(api_client.create_employee(
        create_employee_payload(department_id, **overrides), HR
    ))


def create_budget(program_id, department_id, **overrides) -> dict:
    """Create a point budget (lands OPEN with zeroed counters)."""
    return get_success_data(api_client.create_budget(
        create_budget_payload(program_id, department_id, **overrides), FIN
    ))


def create_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(create_vendor_payload(**overrides), VOPS))


def create_catalog_item(vendor_id, **overrides) -> dict:
    return get_success_data(api_client.create_catalog_item(
        create_catalog_item_payload(vendor_id, **overrides), VOPS
    ))


# ─── Tier 2: org hierarchy ──────────────────────────────────────────────────

def setup_org(num_extra_employees=0, department_name="Eng", **employee_defaults):
    """Department + manager + one report + optional extra employees.

    Returns (dept, manager, employee, extra_employees_list).
    The employee reports to the manager (manager_id set).
    """
    dept = create_department(name=department_name,
                             chargeback_account_code=f"GL-{department_name.upper()}")
    manager = create_employee(
        dept["id"],
        full_name="Mgr One", hire_date="2020-03-01",
        state_code=employee_defaults.get("state_code", "CA"),
    )
    employee = create_employee(
        dept["id"],
        full_name="Emp One", manager_id=manager["id"],
        hire_date=employee_defaults.get("hire_date", "2021-06-15"),
        state_code=employee_defaults.get("state_code", "CA"),
    )
    extras = [
        create_employee(dept["id"], hire_date="2022-01-10",
                        state_code=employee_defaults.get("state_code", "CA"))
        for _ in range(num_extra_employees)
    ]
    return dept, manager, employee, extras


def setup_program_with_budget(program_overrides=None, allocated_points=TEST_DEFAULTS["ALLOCATED_POINTS"],
                              department_name="Eng", num_extra_employees=0,
                              budget_overrides=None, employee_defaults=None):
    """ACTIVE program + department + manager/report pair + funded budget.

    Returns dict with keys: program, dept, manager, employee, extras, budget.
    """
    program = create_and_activate_program(**(program_overrides or {}))
    dept, manager, employee, extras = setup_org(
        num_extra_employees=num_extra_employees,
        department_name=department_name,
        **(employee_defaults or {}),
    )
    budget_kwargs = {"allocated_points": allocated_points}
    budget_kwargs.update(budget_overrides or {})
    budget = create_budget(program["id"], dept["id"], **budget_kwargs)
    return {
        "program": program, "dept": dept, "manager": manager,
        "employee": employee, "extras": extras, "budget": budget,
    }


# ─── Tier 3: nomination / redemption lifecycle shortcuts ────────────────────

def submit_nomination(program_id, nominee_id, nominator, points_requested,
                      type="MANAGER", reason_code="DELIVERY", idempotency_key=None,
                      nominator_role=None):
    """Submit a nomination as the given nominator employee.

    nominator_role inferred: MANAGER type defaults to the Manager role,
    PEER type to the Employee role; override with nominator_role.
    Returns the created nomination.
    """
    key = idempotency_key or f"nom-{program_id[:8]}-{nominator['id'][:8]}-{points_requested}-{reason_code}"
    payload = create_nomination_payload(
        program_id, nominee_id, type=type, points_requested=points_requested,
        reason_code=reason_code, idempotency_key=key,
    )
    if nominator_role == "Manager" or (nominator_role is None and type == "MANAGER"):
        headers = make_manager_headers(nominator["id"])
    else:
        headers = make_employee_headers(nominator["id"])
    return get_success_data(api_client.create_nomination(payload, headers))


def submit_and_approve_nomination(program_id, nominee_id, nominator, points_requested,
                                  type="MANAGER", reason_code="DELIVERY",
                                  idempotency_key=None, approver_headers=None):
    """Submit + approve. Returns (nomination, award_id)."""
    nomination = submit_nomination(
        program_id, nominee_id, nominator, points_requested,
        type=type, reason_code=reason_code, idempotency_key=idempotency_key,
    )
    approved = get_success_data(api_client.approve_nomination(
        nomination["id"], nomination["version"], approver_headers or HR
    ))
    return approved, approved["award_id"]


def setup_employee_with_grant(points=1000, program_overrides=None, allocated_points=None):
    """Program + org + budget + one approved MANAGER grant to the employee.

    Returns dict with keys: program, dept, manager, employee, budget,
    nomination, award_id.
    """
    ctx = setup_program_with_budget(
        program_overrides=program_overrides,
        allocated_points=allocated_points or max(TEST_DEFAULTS["ALLOCATED_POINTS"], points * 10),
    )
    nomination, award_id = submit_and_approve_nomination(
        ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], points,
    )
    ctx.update({"nomination": nomination, "award_id": award_id})
    return ctx


def setup_catalog(item_overrides=None, vendor_overrides=None):
    """Vendor + one catalog item with a wide-open availability window.

    Returns (vendor, item).
    """
    vendor = create_vendor(**(vendor_overrides or {}))
    item = create_catalog_item(vendor["id"], **(item_overrides or {}))
    return vendor, item


def create_redemption_order(item_id, employee, idempotency_key=None, quantity=1):
    """Create a redemption order as the given employee. Returns the order."""
    payload = create_redemption_order_payload(
        item_id, quantity=quantity,
        idempotency_key=idempotency_key or f"ord-{item_id[:8]}-{employee['id'][:8]}",
    )
    return get_success_data(api_client.create_redemption_order(
        payload, make_employee_headers(employee["id"])
    ))


def deliver_redemption_order(item_id, employee, idempotency_key=None, quantity=1):
    """Create -> submit -> ship -> deliver. Returns the delivered order
    (tax_record_id populated)."""
    order = create_redemption_order(item_id, employee, idempotency_key=idempotency_key,
                                    quantity=quantity)
    get_success_data(api_client.submit_redemption_order(order["id"], VOPS))
    get_success_data(api_client.mark_redemption_order_shipped(order["id"], VOPS))
    return get_success_data(api_client.mark_redemption_order_delivered(order["id"], VOPS))


# ─── Tier 4: abuse / suspension ─────────────────────────────────────────────

def suspend_employee(employee_id, program_id):
    """Raise + confirm a MANUAL_REVIEW abuse flag; employee lands SUSPENDED.
    Returns the confirmed flag."""
    flag = get_success_data(api_client.create_abuse_flag(
        create_abuse_flag_payload(employee_id, program_id), HR
    ))
    return get_success_data(api_client.confirm_abuse_flag(flag["id"], HR))


# ─── Tier 5: accrual / tax-year finalization ────────────────────────────────

def create_reconcile_close_run(program_id, year, month):
    """Create -> reconcile -> close one monthly accrual run. Returns the CLOSED run."""
    run = get_success_data(api_client.create_accrual_run(
        {"program_id": program_id, "period_year": year, "period_month": month}, FIN
    ))
    get_success_data(api_client.reconcile_accrual_run(run["id"], FIN))
    return get_success_data(api_client.close_accrual_run(run["id"], FIN))


def close_accrual_year(program_id, year, months=range(1, 13)):
    """Create + reconcile + close accrual runs for the given months (default: all 12)."""
    return [create_reconcile_close_run(program_id, year, month) for month in months]
