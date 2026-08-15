"""Pre-built role headers for every role in the PRD (section 2.1).

The Employee role is entity-backed: X-User-ID must be the acting Employee's id
whenever the call is ownership-gated, so tests and fixtures must build those
headers per employee via make_employee_headers(). The opaque operator roles
(ParkingAdmin, PayrollAdmin, EnforcementOfficer, AppealsOfficer,
ShuttleDispatcher) can use the shared constants; officer builders exist for
workflows that compare operator ids (issued_by / decided_by / authorized_by).
"""
from prd_bench_local_runner.testing import build_user_headers

PARKING_ADMIN_ID = "test-parking-admin-1"
PAYROLL_ADMIN_ID = "test-payroll-admin-1"
ENFORCEMENT_OFFICER_ID = "officer-1"
APPEALS_OFFICER_ID = "appeals-1"
SHUTTLE_DISPATCHER_ID = "dispatcher-1"

TEST_USERS = {
    # Opaque operator roles: shared constant is the canonical form.
    "parking_admin_headers": build_user_headers(PARKING_ADMIN_ID, "ParkingAdmin"),
    "payroll_admin_headers": build_user_headers(PAYROLL_ADMIN_ID, "PayrollAdmin"),
    "enforcement_officer_headers": build_user_headers(
        ENFORCEMENT_OFFICER_ID, "EnforcementOfficer"
    ),
    "appeals_officer_headers": build_user_headers(APPEALS_OFFICER_ID, "AppealsOfficer"),
    "shuttle_dispatcher_headers": build_user_headers(
        SHUTTLE_DISPATCHER_ID, "ShuttleDispatcher"
    ),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only (bad payloads, unknown resources). Never use it for a call
    # that is ownership-gated.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_employee_headers(user_id: str) -> dict:
    """Employee is entity-backed: pass the actual Employee.id as user_id for
    any ownership-gated call (permit application, permit events, renewals,
    violation appeals)."""
    return build_user_headers(user_id, "Employee")


def make_parking_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ParkingAdmin")


def make_enforcement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnforcementOfficer")


def make_appeals_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealsOfficer")


def make_payroll_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollAdmin")


def make_shuttle_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShuttleDispatcher")
