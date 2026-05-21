"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee` record; ownership checks on any resource that
    references an employee compare the resource's `employee_id` field
    to `X-User-ID`."

    "When `X-User-Role` is `Supervisor`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity."

    "When `X-User-Role` is `PayrollAdmin`, `X-User-ID` is likewise an
    opaque operator identifier not tied to any persisted entity."

Only ONE role is entity_backed in this PRD: Employee. Every fixture or
test that issues an Employee-acted call against a real shift / time edit
MUST mint headers via `make_employee_headers(employee_id)` with the actual
Employee.id. Falling back to the shared placeholder would force the
implementation to drop the Employee ownership check in order to pass and
is a test bug.

Supervisor and PayrollAdmin are opaque — shared deterministic ids are
the canonical form. PRD §2.1 also imposes a segregation-of-duties rule
on TimeEdit approval ("the approver's `X-User-ID` does not equal
`requested_by_user_id` — same person rejects with
`ERR_SEGREGATION_OF_DUTIES`"); per-instance Supervisor /
PayrollAdmin builders are provided so distinct opaque operators can be
modelled in a single test.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
SUPERVISOR_SHARED_ID: str = "supervisor-op-0001"
SUPERVISOR_SECONDARY_ID: str = "supervisor-op-0002"

PAYROLL_ADMIN_SHARED_ID: str = "payroll-admin-op-0001"
PAYROLL_ADMIN_SECONDARY_ID: str = "payroll-admin-op-0002"

# Entity-backed placeholder — never resolves to a real Employee. Used
# only for auth probes, role-forbidden probes, or 404 probes.
EMPLOYEE_PLACEHOLDER_ID: str = "employee-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Employee — shared constant is a placeholder for
    # auth / role / 404 probes only.
    "employee_headers": build_user_headers(
        EMPLOYEE_PLACEHOLDER_ID, "Employee",
    ),
    # opaque Supervisor — shared constants are the canonical form.
    "supervisor_headers": build_user_headers(
        SUPERVISOR_SHARED_ID, "Supervisor",
    ),
    "supervisor_secondary_headers": build_user_headers(
        SUPERVISOR_SECONDARY_ID, "Supervisor",
    ),
    # opaque PayrollAdmin — shared constants are the canonical form.
    "payroll_admin_headers": build_user_headers(
        PAYROLL_ADMIN_SHARED_ID, "PayrollAdmin",
    ),
    "payroll_admin_secondary_headers": build_user_headers(
        PAYROLL_ADMIN_SECONDARY_ID, "PayrollAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Employee role.
# PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id`
# of the acting `Employee` record".
# ---------------------------------------------------------------------------
def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an Employee acting on behalf of `employee_id`.

    Required whenever the call exercises an ownership check against the
    employee — punches against the employee's own shifts, TimeEdit
    submission against own shifts, GET on own shift / workweek, and tip
    declaration on own shift (PRD §2.1).
    """
    return build_user_headers(employee_id, "Employee")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful for tests that need
# two distinct Supervisor / PayrollAdmin operators in the same scenario
# (e.g., segregation-of-duties enforcement, concurrent writes).
# ---------------------------------------------------------------------------
def make_supervisor_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a Supervisor with a specific opaque operator id.

    PRD §2.1: "When `X-User-Role` is `Supervisor`, `X-User-ID` is an
    opaque operator identifier not tied to any persisted entity."
    """
    return build_user_headers(operator_id, "Supervisor")


def make_payroll_admin_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a PayrollAdmin with a specific opaque operator id.

    PRD §2.1: "When `X-User-Role` is `PayrollAdmin`, `X-User-ID` is
    likewise an opaque operator identifier not tied to any persisted
    entity."
    """
    return build_user_headers(operator_id, "PayrollAdmin")


__all__ = [
    "SUPERVISOR_SHARED_ID",
    "SUPERVISOR_SECONDARY_ID",
    "PAYROLL_ADMIN_SHARED_ID",
    "PAYROLL_ADMIN_SECONDARY_ID",
    "EMPLOYEE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_employee_headers",
    "make_supervisor_headers",
    "make_payroll_admin_headers",
]
