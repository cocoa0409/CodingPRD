"""Pre-built role headers for every role in the Campus Shuttle PRD.

PRD §2.1 identity rules:

- Dispatcher carries an OPAQUE X-User-ID: "an opaque operator identifier
  not tied to any persisted entity. The server may record it (for example,
  as actor_id on an audit log entry that a state transition writes) but
  does not compare it to any entity's id." Shared constants are safe.

- Driver is ENTITY-BACKED:Driver: "When X-User-Role is Driver, X-User-ID
  is the id of the acting Driver row; ownership checks on any resource
  that references a Driver (for example, assigned_driver_id on a daily
  run-sheet) compare the resource's foreign-key field to X-User-ID." Any
  Driver-role call whose success depends on ownership of the subject
  resource MUST use make_driver_headers(driver["id"]) — passing a
  shared fallback constant guarantees the ownership check fails for every
  real driver id, cascading "Setup failed" into every downstream test.

- Employee carries an OPAQUE X-User-ID that "is carried through to the
  employee_id field on a new reservation and used to scope cancellation
  and listing of that employee's own reservations." It is NOT joined
  against any persisted Employee row. To stay PRD-faithful and avoid
  ambiguity between (a) implementations that copy employee_id from the
  body and (b) implementations that copy from X-User-ID, the
  per-instance builder make_employee_headers(employee_id) returns a
  header set whose X-User-ID equals the body employee_id. Every
  reservation-cancel and employee-scope test in fixtures uses it.

- Auditor carries an OPAQUE X-User-ID with the same recording semantics
  as Dispatcher. Shared constants are safe.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque — canonical constants.
    "dispatcher_headers": build_user_headers(
        "dispatcher-001", "Dispatcher",
    ),
    "dispatcher_headers_alt": build_user_headers(
        "dispatcher-002", "Dispatcher",
    ),
    "auditor_headers": build_user_headers(
        "auditor-001", "Auditor",
    ),
    # Driver fallback — use ONLY for tests that do not exercise ownership
    # (e.g., 401/403 envelope checks). PRD §2.1 requires real Driver-role
    # calls to set X-User-ID to the acting Driver.id. Fixtures and tests
    # MUST use make_driver_headers(driver["id"]) for ownership-gated calls.
    "driver_headers": build_user_headers(
        "driver-fallback", "Driver",
    ),
    # Employee fallback — use ONLY for tests that do not depend on the
    # cancel/list employee-scoping semantics described in PRD §2.1.
    "employee_headers": build_user_headers(
        "employee-fallback", "Employee",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """PRD §2.1: "When X-User-Role is Driver, X-User-ID is the id of the
    acting Driver row." Pass the actual Driver.id returned by POST
    /shuttle/drivers whenever the downstream call is ownership-gated."""
    return build_user_headers(driver_id, "Driver")


def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """PRD §2.1: Employee X-User-ID "is carried through to the
    employee_id field on a new reservation and used to scope cancellation
    and listing of that employee's own reservations." Tests should set
    X-User-ID equal to the body employee_id so the cancel-window /
    listing scope checks resolve regardless of whether the implementation
    derives employee_id from the body or from the header."""
    return build_user_headers(employee_id, "Employee")


def make_dispatcher_headers(user_id: str = "dispatcher-001") -> Dict[str, str]:
    """PRD §2.1: Dispatcher X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "Dispatcher")


def make_auditor_headers(user_id: str = "auditor-001") -> Dict[str, str]:
    """PRD §2.1: Auditor X-User-ID is an opaque read-only operator id."""
    return build_user_headers(user_id, "Auditor")


__all__ = [
    "TEST_USERS",
    "make_driver_headers",
    "make_employee_headers",
    "make_dispatcher_headers",
    "make_auditor_headers",
]
