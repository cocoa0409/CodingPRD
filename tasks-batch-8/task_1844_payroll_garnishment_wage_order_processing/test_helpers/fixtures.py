"""Composite setup helpers for garnishment/wage-order test scenarios.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server restarts before each test, so nothing carries over).
Setup calls use the lenient get_success_data() validator so failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

OCC threading rules honoured here (PRD §2.7, §2.8):
- employer version is re-read before every expected_employer_version call,
- employee version is re-read before every order intake (order receipt bumps
  the employee's version through a cascade).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_START, PAY_DATE, PERIOD_END, PERIOD_START
from .factories import (
    clock_payload,
    create_authority_payload,
    create_employee_payload,
    create_employer_payload,
    create_order_payload,
    create_payroll_run_payload,
    create_remittance_payload,
    create_state_rule_payload,
    create_statement_payload,
    pay_run_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
MANAGER = TEST_USERS["manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- Tier 0: clock / reference data -----------------------------------------


def set_clock(to_iso8601: str = CLOCK_START):
    return get_success_data(api.set_clock(clock_payload(to_iso8601), ADMIN))


def make_state_rule(state_code="CA", **overrides):
    payload = create_state_rule_payload(state_code=state_code, **overrides)
    return get_success_data(api.create_state_rule(payload, ADMIN))


def get_state_rule(state_code, headers=SPECIALIST):
    return get_success_data(api.get_state_rule(state_code, headers))


def make_authority(**overrides):
    return get_success_data(api.create_authority(create_authority_payload(**overrides), ADMIN))


def make_employer(**overrides):
    return get_success_data(api.create_employer(create_employer_payload(**overrides), ADMIN))


# --- Tier 0.5: OCC version readers -------------------------------------------


def employer_version(employer_id) -> int:
    return get_success_data(api.get_employer(employer_id, SPECIALIST))["version"]


def employee_version(employee_id) -> int:
    return get_success_data(api.get_employee(employee_id, SPECIALIST))["version"]


# --- Tier 2: entity hierarchy -------------------------------------------------


def make_employee(employer_id, **overrides):
    payload = create_employee_payload(
        employer_id, employer_version(employer_id), **overrides
    )
    return get_success_data(api.create_employee(payload, SPECIALIST))


def setup_employer_with_employee(state_code="CA", state_rule_overrides=None,
                                 employer_overrides=None, employee_overrides=None,
                                 authority_overrides=None, clock=CLOCK_START):
    """State rule + employer + employee + child-support authority.

    Returns dict(state_rule, employer, employee, authority).
    """
    set_clock(clock)
    state_rule = make_state_rule(state_code=state_code, **(state_rule_overrides or {}))
    authority = make_authority(**(authority_overrides or {}))
    employer = make_employer(**(employer_overrides or {}))
    employee = make_employee(employer["id"], **(employee_overrides or {}))
    return {
        "state_rule": state_rule,
        "authority": authority,
        "employer": employer,
        "employee": employee,
    }


# --- Tier 1: order state progression ------------------------------------------


def receive_order(employee_id, authority_id, **overrides):
    """Order intake with a freshly read expected_employee_version."""
    payload = create_order_payload(
        authority_id, employee_version(employee_id), **overrides
    )
    return get_success_data(api.create_order(employee_id, payload, SPECIALIST))


def validate_order(order_id):
    return get_success_data(api.validate_order(order_id, SPECIALIST))


def notify_order(order_id):
    return get_success_data(api.notify_order(order_id, SPECIALIST))


def activate_order(order_id):
    return get_success_data(api.activate_order(order_id, SPECIALIST))


def drive_order_to_active(order_id):
    """Walk an order RECEIVED -> VALIDATED -> EMPLOYEE_NOTIFIED -> ACTIVE."""
    validate_order(order_id)
    notify_order(order_id)
    return activate_order(order_id)


def suspend_order(order_id, hold_reason="DISPUTED"):
    return get_success_data(
        api.suspend_order(order_id, {"hold_reason": hold_reason}, MANAGER)
    )


def resume_order(order_id):
    return get_success_data(api.resume_order(order_id, MANAGER))


def get_order(order_id):
    return get_success_data(api.get_order(order_id, SPECIALIST))


# --- Tier 2/3: payroll runs and statements -------------------------------------


def make_open_run(employer_id, period_start=PERIOD_START, period_end=PERIOD_END,
                  pay_date=PAY_DATE):
    payload = create_payroll_run_payload(
        employer_id,
        employer_version(employer_id),
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
    )
    return get_success_data(api.create_payroll_run(payload, SPECIALIST))


def add_statement(run_id, employee_id, hours_worked=None, **overrides):
    payload = create_statement_payload(employee_id, **overrides)
    if hours_worked is not None:
        payload["hours_worked"] = hours_worked
    return get_success_data(api.create_statement(run_id, payload, SPECIALIST))


def pay_run_fresh(employer_id, run_id):
    """Pay a run with a freshly read expected_employer_version."""
    payload = pay_run_payload(employer_version(employer_id))
    return get_success_data(api.pay_run(run_id, payload, SPECIALIST))


def get_statement(statement_id):
    return get_success_data(api.get_statement(statement_id, SPECIALIST))


def get_payroll_run(run_id):
    return get_success_data(api.get_payroll_run(run_id, SPECIALIST))


def list_order_events(order_id):
    return get_success_data(api.list_order_events(order_id, SPECIALIST))


# --- Tier 3: full lifecycle shortcuts -------------------------------------------


def setup_active_order_scenario(order_overrides=None, **base_kwargs):
    """Employer + employee + authority + one ACTIVE order.

    Returns dict(state_rule, authority, employer, employee, order).
    """
    base = setup_employer_with_employee(**base_kwargs)
    order = receive_order(
        base["employee"]["id"], base["authority"]["id"], **(order_overrides or {})
    )
    drive_order_to_active(order["id"])
    base["order"] = get_order(order["id"])
    return base


def setup_paid_single_order(order_overrides=None, statement_overrides=None,
                            hours_worked=None, run_kwargs=None, **base_kwargs):
    """Full pipeline through PAID with one ACTIVE order on the statement's employee.

    Returns dict(..., order, run, statement).
    """
    base = setup_active_order_scenario(order_overrides=order_overrides, **base_kwargs)
    run = make_open_run(base["employer"]["id"], **(run_kwargs or {}))
    statement = add_statement(
        run["id"], base["employee"]["id"],
        hours_worked=hours_worked, **(statement_overrides or {}),
    )
    pay_run_fresh(base["employer"]["id"], run["id"])
    base.update({
        "run": get_payroll_run(run["id"]),
        "statement": get_statement(statement["id"]),
        "order": get_order(base["order"]["id"]),
    })
    return base


def setup_paid_two_orders(order_a_overrides=None, order_b_overrides=None,
                          statement_overrides=None, hours_worked=None,
                          **base_kwargs):
    """Full pipeline through PAID with two ACTIVE orders on one employee.

    Returns dict(..., order_a, order_b, run, statement).
    """
    base = setup_employer_with_employee(**base_kwargs)
    order_a = receive_order(
        base["employee"]["id"], base["authority"]["id"], **(order_a_overrides or {})
    )
    order_b = receive_order(
        base["employee"]["id"], base["authority"]["id"], **(order_b_overrides or {})
    )
    drive_order_to_active(order_a["id"])
    drive_order_to_active(order_b["id"])
    run = make_open_run(base["employer"]["id"])
    statement = add_statement(
        run["id"], base["employee"]["id"],
        hours_worked=hours_worked, **(statement_overrides or {}),
    )
    pay_run_fresh(base["employer"]["id"], run["id"])
    base.update({
        "order_a": get_order(order_a["id"]),
        "order_b": get_order(order_b["id"]),
        "run": get_payroll_run(run["id"]),
        "statement": get_statement(statement["id"]),
    })
    return base


# --- Tier 3.5: remittances --------------------------------------------------------


def make_remittance(employer_id, authority_id, run_id):
    payload = create_remittance_payload(employer_id, authority_id, run_id)
    return get_success_data(api.create_remittance(payload, SPECIALIST))


def get_remittance(remittance_id):
    return get_success_data(api.get_remittance(remittance_id, SPECIALIST))


def setup_pending_remittance(**kwargs):
    """Paid run with one ACTIVE order plus a PENDING remittance for the authority.

    Returns dict(..., order, run, statement, remittance).
    """
    base = setup_paid_single_order(**kwargs)
    remittance = make_remittance(
        base["employer"]["id"], base["authority"]["id"], base["run"]["id"]
    )
    base["remittance"] = remittance
    return base
