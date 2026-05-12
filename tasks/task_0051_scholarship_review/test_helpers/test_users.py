"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- SchoolAdmin, DeptOfficer, FinanceOfficer, Student all carry OPAQUE
  X-User-IDs: 'X-User-ID is an opaque operator identifier not tied to any
  persisted entity. The server may record it in audit and approval-tracking
  fields ... but it does not compare these opaque identifiers to any
  entity's id.'

- Reviewer is ENTITY-BACKED: 'For Reviewer, X-User-ID is the id of the
  acting Reviewer entity in the reviewer pool. Ownership checks on score
  submission compare the target application's ReviewerAssignment.reviewer_id
  to X-User-ID; only a reviewer with a live assignment for a given
  application may submit a Score for it.'

- For Student: even though X-User-ID is opaque, PRD §2.1 also states:
  'A Student principal's X-User-ID is, by convention, stamped onto every
  Application they create as the student_id, and ownership comparisons
  (such as withdraw / modify / correct authorisation) compare the
  application's student_id to the requester's X-User-ID literally.' So
  ownership comparisons between two different students still require
  distinct X-User-IDs — the per-instance Student builder solves that.

- DeptOfficer: PRD §3.4 'only when the officer's own department code
  matches the application's student_department_code'. The department
  scope check compares the officer's HOME DEPARTMENT to the application's
  student_department_code. Since DeptOfficer is opaque, the department
  identification needs to come through X-User-ID — by convention the
  per-instance builder stamps the department code into the user id so
  the implementation can resolve it. Tests use distinct X-User-IDs for
  same-dept vs different-dept officers.

- DisbursementPlan dept_approver_id and finance_approver_id (PRD §3.10):
  these record the requester's X-User-ID at approval time, so SOD and
  executor-mismatch checks compare X-User-IDs. The opaque-id-pair pattern
  is fine here as long as the two principals have DIFFERENT X-User-IDs.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants. Canonical for SchoolAdmin (the only true
# pure-opaque role used across many test calls). DeptOfficer / FinanceOfficer
# / Student / Reviewer should use per-instance builders so principals can be
# distinguished in SOD / executor-mismatch / ownership / COI tests.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque admin — canonical constant.
    "school_admin_headers": build_user_headers(
        "admin-001", "SchoolAdmin",
    ),
    "school_admin_headers_alt": build_user_headers(
        "admin-002", "SchoolAdmin",
    ),

    # Fallback constants for opaque-but-distinguishable roles. Use ONLY
    # when the test does not care about identity (ERR_AUTH_MISSING,
    # ERR_FORBIDDEN by wrong role, ERR_NOT_FOUND on missing resource).
    "dept_officer_headers": build_user_headers(
        "dept-officer-fallback", "DeptOfficer",
    ),
    "finance_officer_headers": build_user_headers(
        "finance-officer-fallback", "FinanceOfficer",
    ),
    "student_headers": build_user_headers(
        "student-fallback", "Student",
    ),
    "reviewer_headers": build_user_headers(
        "reviewer-fallback", "Reviewer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Use these whenever the call is identity-gated.
# ---------------------------------------------------------------------------
def make_school_admin_headers(admin_id: str = "admin-001") -> Dict[str, str]:
    """PRD §2.1: SchoolAdmin X-User-ID is an opaque operator id; the
    server records but does not match it against any entity."""
    return build_user_headers(admin_id, "SchoolAdmin")


def make_student_headers(student_id: str) -> Dict[str, str]:
    """PRD §2.1: 'A Student principal's X-User-ID is, by convention,
    stamped onto every Application they create as the student_id, and
    ownership comparisons (such as withdraw / modify / correct
    authorisation) compare the application's student_id to the
    requester's X-User-ID literally.' Pass a unique student_id per
    student so ownership tests can distinguish principals."""
    return build_user_headers(student_id, "Student")


def make_dept_officer_headers(officer_id: str) -> Dict[str, str]:
    """PRD §2.1 / §3.4: DeptOfficer is opaque, but department scope check
    requires the officer's home department to be known to the server. By
    convention, distinct X-User-IDs identify distinct DeptOfficers; tests
    that need a specific department use officer_id strings the
    implementation can resolve (e.g., 'dept-officer-CS-001' for CS, but
    the binding is implementation-defined). Tests should treat the same
    officer_id as 'same DeptOfficer' across calls."""
    return build_user_headers(officer_id, "DeptOfficer")


def make_finance_officer_headers(officer_id: str) -> Dict[str, str]:
    """PRD §3.10: 'the plan's `dept_approver_id` is set to the requesting
    DeptOfficer's X-User-ID' / 'the `finance_approver_id` is set to the
    requester's X-User-ID'. SOD check: 'the requester's X-User-ID must
    differ from the plan's dept_approver_id'. Executor check: 'the same
    FinanceOfficer whose X-User-ID equals the plan's finance_approver_id'.
    Tests must use distinct X-User-IDs so SOD and executor identity can
    be exercised."""
    return build_user_headers(officer_id, "FinanceOfficer")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'For Reviewer, X-User-ID is the id of the acting Reviewer
    entity in the reviewer pool. Ownership checks on score submission
    compare the target application's ReviewerAssignment.reviewer_id to
    X-User-ID.' Pass the actual Reviewer.id minted by POST /reviewers."""
    return build_user_headers(reviewer_id, "Reviewer")


__all__ = [
    "TEST_USERS",
    "make_school_admin_headers",
    "make_student_headers",
    "make_dept_officer_headers",
    "make_finance_officer_headers",
    "make_reviewer_headers",
]
