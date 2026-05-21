"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "The remaining four roles — `HRBP`, `Manager`, `Reviewer`, and
    `Approver` — are all entity-backed: when `X-User-Role` carries one
    of those four values, `X-User-ID` is the `id` of the acting
    `Employee`, and ownership checks on any resource that references an
    `Employee` (manager checks on a `ReviewCase`, reviewer checks on a
    `FeedbackRequest`, approver-vs-manager segregation checks on a
    `CompPlan`) compare the resource's foreign-key field to
    `X-User-ID`."

    "When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server may record
    it (for example, as `actor_user_id` on the audit ledger) but does
    not compare it to any entity's `id`."

That means:

* Admin is opaque — a shared deterministic id is the canonical form.
* HRBP, Manager, Reviewer, Approver are entity_backed:Employee. Every
  fixture or test that issues such a call against a real resource MUST
  mint headers via `make_<role>_headers(employee_id)` with the actual
  acting Employee.id. Falling back to a shared placeholder forces the
  implementation to drop the ownership check (manager-of-case,
  reviewer-of-feedback, approver-not-manager segregation) in order to
  pass — that is the canonical setup-bug pattern and the test is
  responsible for preventing it.

Shared-constant entries below are reserved for tests that do NOT exercise
ownership, namely:
  - Auth-required probes (missing / wrong headers).
  - Role-forbidden probes (wrong role for endpoint).
  - 404 probes (resource does not exist; ownership cannot be checked).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids — for the OPAQUE Admin role only, plus
# placeholders for the four entity_backed roles used by auth / 404 probes.
# ---------------------------------------------------------------------------
ADMIN_SHARED_ID: str = "admin-op-0001"
ADMIN_SECONDARY_ID: str = "admin-op-0002"

# Entity-backed placeholders — DO NOT match any real Employee.id.
# Use only for tests that do not exercise an ownership check.
HRBP_PLACEHOLDER_ID: str = "00000000-0000-4000-8000-00000000aaaa"
MANAGER_PLACEHOLDER_ID: str = "00000000-0000-4000-8000-00000000bbbb"
REVIEWER_PLACEHOLDER_ID: str = "00000000-0000-4000-8000-00000000cccc"
APPROVER_PLACEHOLDER_ID: str = "00000000-0000-4000-8000-00000000dddd"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Admin (opaque) — shared constant is canonical.
    "admin_headers": build_user_headers(ADMIN_SHARED_ID, "Admin"),
    "admin_secondary_headers": build_user_headers(
        ADMIN_SECONDARY_ID, "Admin",
    ),

    # entity_backed placeholders — for auth / role / 404 probes only.
    "hrbp_placeholder_headers": build_user_headers(
        HRBP_PLACEHOLDER_ID, "HRBP",
    ),
    "manager_placeholder_headers": build_user_headers(
        MANAGER_PLACEHOLDER_ID, "Manager",
    ),
    "reviewer_placeholder_headers": build_user_headers(
        REVIEWER_PLACEHOLDER_ID, "Reviewer",
    ),
    "approver_placeholder_headers": build_user_headers(
        APPROVER_PLACEHOLDER_ID, "Approver",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for every entity_backed role acting on
# any ownership-checked path. Always pass the acting Employee.id.
# PRD §2.1: "X-User-ID is the id of the acting Employee".
# ---------------------------------------------------------------------------
def make_admin_headers(operator_id: str) -> Dict[str, str]:
    """Admin is opaque (PRD §2.1). Useful for tests that need two
    distinct opaque operator ids in the same scenario (audit-attribution
    checks)."""
    return build_user_headers(operator_id, "Admin")


def make_hrbp_headers(employee_id: str) -> Dict[str, str]:
    """HRBP is entity_backed:Employee (PRD §2.1). Pass the acting HRBP's
    Employee.id. HRBP owns cycle lifecycle, calibration, PIP processing.
    The facilitator-conflict rule (PRD §2.11) compares this id to the
    pinned manager_employee_id of every covered ReviewCase."""
    return build_user_headers(employee_id, "HRBP")


def make_manager_headers(employee_id: str) -> Dict[str, str]:
    """Manager is entity_backed:Employee (PRD §2.1). Pass the acting
    Manager's Employee.id. The submit/return/reopen and goal-edit paths
    compare this id to ReviewCase.manager_employee_id."""
    return build_user_headers(employee_id, "Manager")


def make_reviewer_headers(employee_id: str) -> Dict[str, str]:
    """Reviewer is entity_backed:Employee (PRD §2.1). Pass the acting
    Reviewer's Employee.id. The feedback-request submit/decline path
    requires the acting reviewer to equal
    FeedbackRequest.reviewer_employee_id (PRD §3.4)."""
    return build_user_headers(employee_id, "Reviewer")


def make_approver_headers(employee_id: str) -> Dict[str, str]:
    """Approver is entity_backed:Employee (PRD §2.1). Pass the acting
    Approver's Employee.id. The approver-is-manager segregation check
    (PRD §2.11) compares this id to the pinned ReviewCase
    manager_employee_id."""
    return build_user_headers(employee_id, "Approver")


__all__ = [
    "ADMIN_SHARED_ID",
    "ADMIN_SECONDARY_ID",
    "HRBP_PLACEHOLDER_ID",
    "MANAGER_PLACEHOLDER_ID",
    "REVIEWER_PLACEHOLDER_ID",
    "APPROVER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_admin_headers",
    "make_hrbp_headers",
    "make_manager_headers",
    "make_reviewer_headers",
    "make_approver_headers",
]
