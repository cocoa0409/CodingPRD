"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- SiteManager, PlanOwner, Dispatcher, Storekeeper: 'X-User-ID is an opaque
  operator identifier not tied to any persisted entity. The server records
  it in audit entries as actor_user_id, but never compares it to any
  entity's id.' Shared TEST_USERS constants are canonical for these.

- SiteManager has one ownership-flavoured exception: 'when a SiteManager
  accepts a completed work order, X-User-ID must equal the
  responsible_user_id recorded on the equipment'. So an /accept call needs
  an X-User-ID that matches the equipment's responsible_user_id;
  make_site_manager_headers(responsible_user_id) builds that.

- Technician: 'When X-User-Role is Technician, X-User-ID is the id of the
  acting Technician entity within the addressed site. Ownership checks on
  a WorkOrder compare WorkOrder.assigned_technician_id to X-User-ID.'
  Technician is entity-backed: ownership-gated calls (start, pause, resume,
  complete) MUST use make_technician_headers(technician.id).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants for role-permission tests where ownership does NOT matter
# (e.g., wrong-role 403 tests, ERR_NOT_FOUND on missing resource).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical for non-ownership-gated work.
    "site_manager_headers": build_user_headers(
        "site-manager-001", "SiteManager"
    ),
    "site_manager_headers_alt": build_user_headers(
        "site-manager-002", "SiteManager"
    ),
    "plan_owner_headers": build_user_headers(
        "plan-owner-001", "PlanOwner"
    ),
    "plan_owner_headers_alt": build_user_headers(
        "plan-owner-002", "PlanOwner"
    ),
    "dispatcher_headers": build_user_headers(
        "dispatcher-001", "Dispatcher"
    ),
    "dispatcher_headers_alt": build_user_headers(
        "dispatcher-002", "Dispatcher"
    ),
    "storekeeper_headers": build_user_headers(
        "storekeeper-001", "Storekeeper"
    ),
    "storekeeper_headers_alt": build_user_headers(
        "storekeeper-002", "Storekeeper"
    ),
    # Fallback for Technician — ONLY for non-ownership tests (e.g., RBAC
    # wrong-role checks, ERR_NOT_FOUND on missing WO). Ownership-gated tests
    # MUST build per-instance headers via make_technician_headers().
    "technician_headers": build_user_headers(
        "technician-fallback-001", "Technician"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed role.
# ---------------------------------------------------------------------------
def make_technician_headers(technician_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Technician, X-User-ID is the id of
    the acting Technician entity within the addressed site. Ownership
    checks on a WorkOrder compare WorkOrder.assigned_technician_id to
    X-User-ID; a mismatch yields ERR_FORBIDDEN_NOT_OWNER.'

    Pass the actual Technician.id whenever the call is ownership-gated:
    /start, /pause, /resume, /complete.
    """
    return build_user_headers(technician_id, "Technician")


# ---------------------------------------------------------------------------
# Per-instance builder for SiteManager when the call is /accept.
# PRD §2.1: 'when a SiteManager accepts a completed work order, X-User-ID
# must equal the responsible_user_id recorded on the equipment, otherwise
# the action is rejected with ERR_FORBIDDEN_NOT_OWNER.'
# ---------------------------------------------------------------------------
def make_site_manager_headers(user_id: str) -> Dict[str, str]:
    """SiteManager headers pinned to a specific X-User-ID. Use when the
    call is /accept (X-User-ID must match Equipment.responsible_user_id) or
    when a test asserts on AuditEntry.actor_user_id.
    """
    return build_user_headers(user_id, "SiteManager")


# ---------------------------------------------------------------------------
# Per-instance builders for the remaining opaque roles. Useful when a test
# pins AuditEntry.actor_user_id or simulates two distinct dispatchers.
# ---------------------------------------------------------------------------
def make_plan_owner_headers(user_id: str = "plan-owner-001") -> Dict[str, str]:
    return build_user_headers(user_id, "PlanOwner")


def make_dispatcher_headers(user_id: str = "dispatcher-001") -> Dict[str, str]:
    return build_user_headers(user_id, "Dispatcher")


def make_storekeeper_headers(user_id: str = "storekeeper-001") -> Dict[str, str]:
    return build_user_headers(user_id, "Storekeeper")


__all__ = [
    "TEST_USERS",
    "make_technician_headers",
    "make_site_manager_headers",
    "make_plan_owner_headers",
    "make_dispatcher_headers",
    "make_storekeeper_headers",
]
