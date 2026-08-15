"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch via the public API (the server
is restarted before each test, so nothing carries over). Setup calls use the
lenient get_success_data() validator so a broken precondition reports a clear
"Setup step failed" message instead of a confusing assertion error.

Ownership threading rule: after an Employee is created, every ownership-gated
call (permit application, ACCEPT/DECLINE/CANCEL permit events, renewal
creation, violation APPEAL) uses make_employee_headers(employee["id"]) —
never the shared TEST_USERS["employee_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import AUGUST_PERIOD_END, AUGUST_PERIOD_START, CLOCK_START
from .factories import (
    close_cycle_payload,
    create_billing_cycle_payload,
    create_charge_entry_payload,
    create_employee_payload,
    create_lot_payload,
    create_permit_payload,
    create_program_payload,
    create_violation_payload,
    cycle_event_payload,
    permit_event_payload,
    settle_payload,
)
from .test_users import TEST_USERS, make_employee_headers, make_enforcement_officer_headers

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ─── Tier 0: clock + single-resource creators ─────────────────────────

def set_logical_clock(to_iso8601: str):
    """Advance the server's logical clock (ParkingAdmin-only test hook)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock():
    return set_logical_clock(CLOCK_START)


def create_program(**overrides) -> dict:
    res = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_employee(program_id: str, badge_number: str = "B001",
                    shift_pattern: str = "DAY", **overrides) -> dict:
    payload = create_employee_payload(
        program_id, badge_number=badge_number, shift_pattern=shift_pattern,
        **overrides,
    )
    return get_success_data(api_client.create_employee(payload, ADMIN))


def create_lot(program_id: str, code: str = "CORE-A", tier: str = "CORE",
               capacity: int = 5, **overrides) -> dict:
    payload = create_lot_payload(
        program_id, code=code, tier=tier, capacity=capacity, **overrides
    )
    return get_success_data(api_client.create_lot(payload, ADMIN))


def open_billing_cycle(program_id: str, period_start: str = AUGUST_PERIOD_START,
                       period_end: str = AUGUST_PERIOD_END) -> dict:
    payload = create_billing_cycle_payload(program_id, period_start, period_end)
    return get_success_data(api_client.create_billing_cycle(payload, PAYROLL))


def apply_for_permit(employee: dict, lot: dict, vehicle_plate: str = "P001") -> dict:
    """Employee self-application (ownership-gated: caller id == employee id)."""
    payload = create_permit_payload(employee["id"], lot["id"],
                                    vehicle_plate=vehicle_plate)
    res = api_client.create_permit(payload, make_employee_headers(employee["id"]))
    return get_success_data(res)


def permit_event(permit_id: str, event_type: str, headers, **extra) -> dict:
    return get_success_data(
        api_client.permit_event(permit_id, permit_event_payload(event_type, **extra),
                                headers)
    )


def accept_permit(permit: dict, employee: dict) -> dict:
    return permit_event(permit["id"], "ACCEPT", make_employee_headers(employee["id"]))


# ─── Tier 1: composite program/lot/cycle setup ────────────────────────

def setup_program_lot_cycle(program_overrides: dict = None,
                            lot_overrides: dict = None,
                            period_start: str = AUGUST_PERIOD_START,
                            period_end: str = AUGUST_PERIOD_END,
                            with_cycle: bool = True) -> dict:
    """Program + one lot (+ optionally an OPEN billing cycle). Keys:
    program, lot, cycle (None when with_cycle is False)."""
    program = create_program(**(program_overrides or {}))
    lot = create_lot(program["id"], **(lot_overrides or {}))
    cycle = None
    if with_cycle:
        cycle = open_billing_cycle(program["id"], period_start, period_end)
    return {"program": program, "lot": lot, "cycle": cycle}


def setup_offered_permit(shift_pattern: str = "DAY",
                         program_overrides: dict = None,
                         lot_overrides: dict = None,
                         with_cycle: bool = True,
                         badge_number: str = "B001",
                         vehicle_plate: str = "P001") -> dict:
    """Program + CORE lot + OPEN cycle + employee whose application resolved
    to OFFERED. Keys: program, lot, cycle, employee, permit."""
    bundle = setup_program_lot_cycle(
        program_overrides=program_overrides, lot_overrides=lot_overrides,
        with_cycle=with_cycle,
    )
    employee = create_employee(bundle["program"]["id"], badge_number=badge_number,
                               shift_pattern=shift_pattern)
    permit = apply_for_permit(employee, bundle["lot"], vehicle_plate=vehicle_plate)
    assert permit["status"] == "OFFERED", (
        f"expected OFFERED, got {permit['status']} — check lot capacity/status"
    )
    bundle.update({"employee": employee, "permit": permit})
    return bundle


def setup_active_permit(shift_pattern: str = "DAY",
                        program_overrides: dict = None,
                        lot_overrides: dict = None,
                        badge_number: str = "B001",
                        vehicle_plate: str = "P001") -> dict:
    """setup_offered_permit + ACCEPT. Keys: program, lot, cycle, employee,
    permit (ACTIVE as returned by the accept call)."""
    bundle = setup_offered_permit(
        shift_pattern=shift_pattern, program_overrides=program_overrides,
        lot_overrides=lot_overrides, with_cycle=True,
        badge_number=badge_number, vehicle_plate=vehicle_plate,
    )
    active = accept_permit(bundle["permit"], bundle["employee"])
    bundle["permit"] = active
    return bundle


# ─── Tier 2: billing cycle progression ────────────────────────────────

def get_cycle_version(cycle_id: str) -> int:
    return get_success_data(api_client.get_billing_cycle(cycle_id, PAYROLL))["version"]


def close_cycle(cycle_id: str) -> dict:
    """Close an OPEN cycle using its freshly read version (OCC)."""
    version = get_cycle_version(cycle_id)
    return get_success_data(
        api_client.close_billing_cycle(cycle_id, close_cycle_payload(version), PAYROLL)
    )


def export_cycle(cycle_id: str) -> dict:
    return get_success_data(
        api_client.billing_cycle_event(cycle_id, cycle_event_payload("EXPORT"), PAYROLL)
    )


def close_and_export_cycle(cycle_id: str) -> dict:
    close_cycle(cycle_id)
    return export_cycle(cycle_id)


def post_adjustment(cycle_id: str, employee_id: str, charge_type: str,
                    amount_cents: int, description: str = None) -> dict:
    overrides = {}
    if description is not None:
        overrides["description"] = description
    payload = create_charge_entry_payload(
        cycle_id, employee_id, charge_type, amount_cents, **overrides
    )
    return get_success_data(api_client.create_charge_entry(payload, PAYROLL))


def settle_entry(entry_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.settle_charge_entry(entry_id, settle_payload(outcome), PAYROLL)
    )


def put_employee_on_billing_hold(cycle_id: str, employee_id: str,
                                 amount_cents: int = 5000) -> dict:
    """Post a debit to the employee, close+export the cycle, then settle the
    debit as DEDUCTION_FAILED so the employee's balance exceeds zero.
    Returns the adjustment entry (now in DEDUCTION_FAILED)."""
    entry = post_adjustment(cycle_id, employee_id, "ADJUSTMENT_DEBIT", amount_cents,
                            description="hold setup")
    close_and_export_cycle(cycle_id)
    return settle_entry(entry["id"], "DEDUCTION_FAILED")


# ─── Tier 3: enforcement setup ────────────────────────────────────────

def issue_violations(permit: dict, violation_code: str = "WRONG_LOT", count: int = 1,
                     officer_id: str = "officer-1") -> list:
    """Issue `count` violations of one code against the permit. Returns the
    created violations in issuance order."""
    headers = make_enforcement_officer_headers(officer_id)
    created = []
    for _ in range(count):
        payload = create_violation_payload(permit["id"], violation_code)
        created.append(get_success_data(api_client.create_violation(payload, headers)))
    return created


def setup_threshold_suspended_permit(violation_code: str = "WRONG_LOT",
                                     threshold: int = 3,
                                     program_overrides: dict = None,
                                     violation_clock: str = "2026-08-10T08:00:00Z",
                                     officer_id: str = "officer-1") -> dict:
    """ACTIVE permit suspended by exactly `threshold` unpaid violations issued
    at `violation_clock`. Keys: program, lot, cycle, employee, permit
    (SUSPENDED), violations."""
    overrides = {"monthly_subsidy_pool_cents": 0,
                 "violation_suspension_threshold": threshold}
    overrides.update(program_overrides or {})
    bundle = setup_active_permit(program_overrides=overrides,
                                 lot_overrides={"capacity": 5})
    set_logical_clock(violation_clock)
    violations = issue_violations(bundle["permit"], violation_code=violation_code,
                                  count=threshold, officer_id=officer_id)
    permit = get_success_data(api_client.get_permit(bundle["permit"]["id"], ADMIN))
    assert permit["status"] == "SUSPENDED", (
        f"expected threshold suspension, got {permit['status']}"
    )
    bundle["permit"] = permit
    bundle["violations"] = violations
    return bundle


# ─── Tier 4: read-side collectors ─────────────────────────────────────

def list_all_charge_entries(headers=None, **params) -> list:
    data, _meta = validate_paginated(
        api_client.list_charge_entries(headers or PAYROLL, params=params)
    )
    return data


def permit_fee_entries(permit_id: str, headers=None) -> list:
    return list_all_charge_entries(headers or PAYROLL, permit_id=permit_id,
                                   charge_type="PERMIT_FEE")


def entries_for_permit(permit_id: str, headers=None) -> list:
    return list_all_charge_entries(headers or PAYROLL, permit_id=permit_id)


def permits_of_lot(lot_id: str, status: str = None, headers=None) -> list:
    params = {"lot_id": lot_id}
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(
        api_client.list_permits(headers or ADMIN, params=params)
    )
    return data


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def get_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, ADMIN))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_billing_cycle(cycle_id, PAYROLL))
