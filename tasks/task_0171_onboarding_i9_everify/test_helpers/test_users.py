"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee`; any ownership check on a resource that references
    an employee compares the resource's `employee_id` to `X-User-ID`.
    When `X-User-Role` is `HRStaff`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity ... When `X-User-Role`
    is `EmployerRep`, `X-User-ID` is likewise an opaque operator
    identifier ... When `X-User-Role` is `System`, `X-User-ID` is an
    arbitrary operator identifier representing test or platform
    automation."

Only ONE role is entity_backed in this PRD: Employee. Every fixture or
test that issues an Employee-acted call (Section 1 attestation, TNC
decision, any GET subject to ownership) MUST mint headers via
`make_employee_headers(employee_id)` with the actual Employee.id.
Falling back to the shared placeholder would force the implementation
to drop the Employee ownership check in order to pass and is a test
bug.

HRStaff, EmployerRep, and System are opaque — shared deterministic ids
are the canonical form. EmployerRep additionally has a "segregation of
duties" rule (PRD §2.1) which is enforced inside ApiClient by passing
distinct EmployerRep ids when needed; helpers `make_employer_rep_headers`
and `make_hr_staff_headers` are provided so multiple distinct EmployerRep
or HRStaff operators can be modelled in a single test.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
HR_STAFF_SHARED_ID: str = "hr-staff-op-0001"
HR_STAFF_SECONDARY_ID: str = "hr-staff-op-0002"

EMPLOYER_REP_SHARED_ID: str = "employer-rep-op-0001"
EMPLOYER_REP_SECONDARY_ID: str = "employer-rep-op-0002"

SYSTEM_SHARED_ID: str = "system-op-0001"

# Entity-backed placeholder — never resolves to a real Employee. Used
# only for auth probes, role-forbidden probes, or 404 probes.
EMPLOYEE_PLACEHOLDER_ID: str = "employee-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Employee — shared constant is a placeholder for
    # auth / role / 404 probes only.
    "employee_headers": build_user_headers(
        EMPLOYEE_PLACEHOLDER_ID, "Employee",
    ),
    # opaque HRStaff — shared constants are the canonical form.
    "hr_staff_headers": build_user_headers(
        HR_STAFF_SHARED_ID, "HRStaff",
    ),
    "hr_staff_secondary_headers": build_user_headers(
        HR_STAFF_SECONDARY_ID, "HRStaff",
    ),
    # opaque EmployerRep — shared constants are the canonical form.
    "employer_rep_headers": build_user_headers(
        EMPLOYER_REP_SHARED_ID, "EmployerRep",
    ),
    "employer_rep_secondary_headers": build_user_headers(
        EMPLOYER_REP_SECONDARY_ID, "EmployerRep",
    ),
    # opaque System — shared constant is the canonical form.
    "system_headers": build_user_headers(
        SYSTEM_SHARED_ID, "System",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Employee role.
# PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id`
# of the acting `Employee`".
# ---------------------------------------------------------------------------
def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """Headers for an Employee acting on behalf of `employee_id`.

    Required whenever the call resolves an ownership check against the
    employee — POST /employees/{employee_id}/i9-forms/{form_id}/section1
    (X-User-ID must equal Employee.id per PRD §3.3),
    POST /everify-cases/{case_id}/tnc-decision (PRD §3.5: "exclusive to
    the `Employee` role, with `X-User-ID` matching the owning employee"),
    and every GET subject to Employee ownership.
    """
    return build_user_headers(employee_id, "Employee")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful for tests that need
# two distinct EmployerRep / HRStaff / System operators in the same
# scenario (e.g., segregation-of-duties enforcement, concurrent writes).
# ---------------------------------------------------------------------------
def make_hr_staff_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an HRStaff with a specific opaque operator id.

    PRD §2.1: "When `X-User-Role` is `HRStaff`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity".
    """
    return build_user_headers(operator_id, "HRStaff")


def make_employer_rep_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an EmployerRep with a specific opaque operator id.

    PRD §2.1: "When `X-User-Role` is `EmployerRep`, `X-User-ID` is
    likewise an opaque operator identifier ... recorded into
    `section2_completed_by_user_id` on the `I9Form` they sign".

    Use a distinct operator_id from the Employee's id to satisfy
    segregation of duties on Section 2.
    """
    return build_user_headers(operator_id, "EmployerRep")


def make_system_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a System operator with a specific opaque id.

    PRD §2.1: "When `X-User-Role` is `System`, `X-User-ID` is an
    arbitrary operator identifier representing test or platform
    automation".
    """
    return build_user_headers(operator_id, "System")


__all__ = [
    "HR_STAFF_SHARED_ID",
    "HR_STAFF_SECONDARY_ID",
    "EMPLOYER_REP_SHARED_ID",
    "EMPLOYER_REP_SECONDARY_ID",
    "SYSTEM_SHARED_ID",
    "EMPLOYEE_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_employee_headers",
    "make_hr_staff_headers",
    "make_employer_rep_headers",
    "make_system_headers",
]
