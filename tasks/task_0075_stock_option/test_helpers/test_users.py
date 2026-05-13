"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlanAdministrator, BoardSecretary, ShareholderRegistrar, AuditViewer
  carry OPAQUE X-User-IDs.
  "When X-User-Role is PlanAdministrator, the X-User-ID is an opaque
  operator identifier not tied to any persisted entity; the server
  records it ... but never compares it to any entity's id." Equivalent
  statements appear for BoardSecretary, ShareholderRegistrar, and
  AuditViewer. Shared constants are canonical for these four roles.

- Grantee is ENTITY-BACKED.
  "When X-User-Role is Grantee, the X-User-ID equals the
  hr_employee_id of exactly one persisted Grantee row; ownership
  checks on any resource that references a Grantee ... compare the
  resource's foreign-key chain back to the Grantee row whose
  hr_employee_id equals X-User-ID."
  Every ownership-gated Grantee call MUST use
  make_grantee_headers(grantee['hr_employee_id']) — passing a shared
  fallback constant guarantees the ownership check fails for every
  real grantee and cascades 'Setup failed' into every downstream test.

Segregation-of-duties (PRD §3.4) further requires that the three
approval actors (submitter, board approver, shareholder approver) on
the same Grant carry DISTINCT X-User-IDs. We therefore expose multiple
"alt" opaque headers so a single test can drive each approval with a
different identifier.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Grantee fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlanAdministrator (opaque) — multiple alts so segregation-of-duties
    # tests can drive draft / board / shareholder transitions with
    # distinct X-User-IDs.
    "plan_admin_headers": build_user_headers(
        "plan-admin-001", "PlanAdministrator",
    ),
    "plan_admin_headers_alt": build_user_headers(
        "plan-admin-002", "PlanAdministrator",
    ),
    "plan_admin_headers_alt2": build_user_headers(
        "plan-admin-003", "PlanAdministrator",
    ),

    # BoardSecretary (opaque)
    "board_secretary_headers": build_user_headers(
        "board-secretary-001", "BoardSecretary",
    ),
    "board_secretary_headers_alt": build_user_headers(
        "board-secretary-002", "BoardSecretary",
    ),

    # ShareholderRegistrar (opaque)
    "shareholder_registrar_headers": build_user_headers(
        "shareholder-registrar-001", "ShareholderRegistrar",
    ),
    "shareholder_registrar_headers_alt": build_user_headers(
        "shareholder-registrar-002", "ShareholderRegistrar",
    ),

    # AuditViewer (opaque, read-only)
    "audit_viewer_headers": build_user_headers(
        "audit-viewer-001", "AuditViewer",
    ),

    # Grantee fallback — use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource).
    # PRD §2.1: real X-User-ID must equal Grantee.hr_employee_id for any
    # ownership-gated call; use make_grantee_headers below in fixtures.
    "grantee_headers": build_user_headers(
        "grantee-fallback", "Grantee",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for the entity_backed Grantee role.
# ---------------------------------------------------------------------------
def make_grantee_headers(hr_employee_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Grantee, the X-User-ID equals the
    hr_employee_id of exactly one persisted Grantee row.' Pass the actual
    Grantee.hr_employee_id returned by POST /option-plans/{planId}/grantees
    whenever the downstream call is ownership-gated (sign-agreement,
    submit-exercise-application, cancel-exercise-application).
    """
    return build_user_headers(hr_employee_id, "Grantee")


def make_plan_admin_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: PlanAdministrator X-User-ID is opaque. Useful when a
    test requires a distinct administrator id (e.g., segregation-of-
    duties scenarios in which the draft submitter must differ from the
    board approver)."""
    return build_user_headers(user_id, "PlanAdministrator")


def make_board_secretary_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: BoardSecretary X-User-ID is opaque."""
    return build_user_headers(user_id, "BoardSecretary")


def make_shareholder_registrar_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: ShareholderRegistrar X-User-ID is opaque."""
    return build_user_headers(user_id, "ShareholderRegistrar")


__all__ = [
    "TEST_USERS",
    "make_grantee_headers",
    "make_plan_admin_headers",
    "make_board_secretary_headers",
    "make_shareholder_registrar_headers",
]
