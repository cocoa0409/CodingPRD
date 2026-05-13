"""Pre-built role headers for the Travel Reimburse API.

PRD §2.1 identity rules:

- The first five roles — Applicant, Supervisor, DeptHead, Finance, and
  GeneralManager — are **entity-backed by Employee**. 'When X-User-Role
  is any of those five values, X-User-ID is the id of the acting
  Employee; ownership checks on any resource that references an Employee
  compare the resource's foreign-key field to X-User-ID.' Concretely,
  ownership of a TravelApplication, Invoice, or ReimbursementForm is
  decided by comparing the resource's applicant_id to X-User-ID;
  supervisory ownership is decided by comparing the owning employee's
  supervisor_id to X-User-ID. The shared-constant entry below is only a
  fallback for tests that do NOT exercise ownership (400-on-bad-payload,
  missing-auth tests, etc.). All ownership-gated calls in fixtures MUST
  thread the actual Employee.id through the per-instance builder
  (make_applicant_headers(employee_id), etc.); otherwise every check
  fails for any real id.

- The Admin role is **opaque** — 'X-User-ID is an opaque operator
  identifier not tied to any persisted Employee row.' The shared
  constant is the canonical form for Admin.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants
#
# - "admin_headers" / "admin_headers_alt": opaque — safe in every test.
# - The five "*_headers" entries below are FALLBACK constants only — they
#   are useful for tests that don't exercise ownership (missing-auth,
#   wrong-role, body-validation). Ownership-gated calls MUST use the
#   per-instance builders below with the actual Employee.id.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Admin — canonical constants.
    "admin_headers": build_user_headers("admin-001", "Admin"),
    "admin_headers_alt": build_user_headers("admin-002", "Admin"),

    # Entity-backed fallbacks. DO NOT use for ownership-gated calls.
    "applicant_headers": build_user_headers(
        "applicant-fallback", "Applicant",
    ),
    "supervisor_headers": build_user_headers(
        "supervisor-fallback", "Supervisor",
    ),
    "dept_head_headers": build_user_headers(
        "dept-head-fallback", "DeptHead",
    ),
    "finance_headers": build_user_headers(
        "finance-fallback", "Finance",
    ),
    "general_manager_headers": build_user_headers(
        "gm-fallback", "GeneralManager",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for every entity-backed role per PRD §2.1.
#
# Pass the actual Employee.id minted by POST /employees as user_id whenever
# the downstream call is ownership-gated (the applicant's own application,
# the supervisor's subordinate's application, the finance officer's payment
# operations, etc.).
# ---------------------------------------------------------------------------
def make_applicant_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'ownership of a TravelApplication, Invoice, or
    ReimbursementForm is decided by comparing the resource's applicant_id
    to X-User-ID.' Pass the actual Employee.id of the applicant."""
    return build_user_headers(user_id, "Applicant")


def make_supervisor_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'supervisory ownership of an applicant's submission is
    decided by comparing the resource's owning employee's supervisor_id
    to X-User-ID.' Pass the Employee.id of the supervisor (the row whose
    id appears as another employee's supervisor_id)."""
    return build_user_headers(user_id, "Supervisor")


def make_dept_head_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: DeptHead is entity-backed by Employee. Pass the
    Employee.id of the dept-head employee."""
    return build_user_headers(user_id, "DeptHead")


def make_finance_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: Finance is entity-backed by Employee. Pass the
    Employee.id of the finance officer."""
    return build_user_headers(user_id, "Finance")


def make_general_manager_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: GeneralManager is entity-backed by Employee. Pass the
    Employee.id of the GM employee."""
    return build_user_headers(user_id, "GeneralManager")


def make_admin_headers(user_id: str = "admin-001") -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Admin, X-User-ID is an opaque
    operator identifier not tied to any persisted Employee row.'"""
    return build_user_headers(user_id, "Admin")


__all__ = [
    "TEST_USERS",
    "make_applicant_headers",
    "make_supervisor_headers",
    "make_dept_head_headers",
    "make_finance_headers",
    "make_general_manager_headers",
    "make_admin_headers",
]
