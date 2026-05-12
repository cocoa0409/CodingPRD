"""Pre-built role headers for every role in the PRD §2.1 RBAC matrix.

PRD §2.1 distinguishes roles by identity binding:

- Public, CrisisResponder, PlatformAdmin: opaque — X-User-ID is NOT compared
  to any persisted entity row.
- Client: entity_backed:Client — when X-User-Role is `Client`, X-User-ID is
  the id of a persisted Client record. Ownership checks (e.g.,
  Appointment.client_id, CounselingRecord.client_id) compare the resource's
  foreign-key field to X-User-ID.
- Counselor: entity_backed:Counselor — X-User-ID must equal Counselor.id.
- Supervisor: entity_backed:Counselor (a senior counselor acting in
  supervisory capacity) — ownership checks for supervision approval/rejection
  compare X-User-ID to SupervisionSession.supervisor_id.

For every entity-backed role, ownership-gated calls MUST use the per-instance
builder make_<role>_headers(actual_entity_id). The shared TEST_USERS constants
exist only as a fallback for tests whose success does NOT depend on the caller
owning a specific resource (e.g., ERR_VALIDATION on bad payload, or
ERR_FORBIDDEN where the role itself is rejected before any ownership check).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership comparisons. Entity-backed fallbacks are SOURCED FROM A NON-UUID
# string deliberately: any test that passes one of these into an
# ownership-gated path will fail the ownership check (which is the correct
# behaviour — those tests should use the make_*_headers builders instead).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "public_headers": build_user_headers("public-001", "Public"),
    "admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "admin_headers_alt": build_user_headers("admin-002", "PlatformAdmin"),
    "crisis_responder_headers": build_user_headers("crisis-001", "CrisisResponder"),
    "crisis_responder_headers_alt": build_user_headers("crisis-002", "CrisisResponder"),

    # Entity-backed fallbacks — for tests that do NOT exercise ownership.
    "client_headers": build_user_headers("client-fallback-001", "Client"),
    "counselor_headers": build_user_headers("counselor-fallback-001", "Counselor"),
    "supervisor_headers": build_user_headers("supervisor-fallback-001", "Supervisor"),
}


# --- Per-instance builders (mandatory for entity-backed roles) -----------
# These thread the actual entity id through X-User-ID so ownership comparisons
# in the implementation succeed for real-world flows. Fixtures that create a
# Client / Counselor MUST use these builders for any downstream
# ownership-gated call.

def make_admin_headers(operator_id: str = "admin-001") -> Dict[str, str]:
    """PlatformAdmin headers; identity is opaque per PRD §2.1.

    Optional operator_id allows distinguishing two admins (e.g., for the
    PRD §3.2 cycle-decision SoD rule, which compares the deciding admin's
    X-User-ID to the supervisor_id of the cycle's required SupervisionSession
    rows).
    """
    return build_user_headers(operator_id, "PlatformAdmin")


def make_crisis_responder_headers(operator_id: str = "crisis-001") -> Dict[str, str]:
    """CrisisResponder headers; identity is opaque per PRD §2.1.

    Optional operator_id distinguishes two responders (e.g., for the
    handover race in PRD §2.12).
    """
    return build_user_headers(operator_id, "CrisisResponder")


def make_client_headers(client_id: str) -> Dict[str, str]:
    """Client headers. PRD §2.1: 'When X-User-Role is Client, X-User-ID is the
    id of a persisted Client record. Ownership checks on any resource that
    references a Client compare the resource's foreign-key field to X-User-ID.'

    Pass the actual Client.id whenever the request is ownership-gated.
    """
    return build_user_headers(client_id, "Client")


def make_counselor_headers(counselor_id: str) -> Dict[str, str]:
    """Counselor headers. PRD §2.1: 'When X-User-Role is Counselor, X-User-ID
    is the id of a persisted Counselor record. A Counselor may only act on
    availability slots, appointments, ... whose counselor_id matches X-User-ID.'

    Pass the actual Counselor.id whenever the request is ownership-gated.
    """
    return build_user_headers(counselor_id, "Counselor")


def make_supervisor_headers(counselor_id: str) -> Dict[str, str]:
    """Supervisor headers. PRD §2.1: 'When X-User-Role is Supervisor, X-User-ID
    is also the id of a persisted Counselor record (a senior counselor acting
    in supervisory capacity). Ownership checks for supervision approval/
    rejection compare X-User-ID to the SupervisionSession's supervisor_id.'

    Pass the actual Counselor.id (acting as supervisor) whenever the call is
    ownership-gated (POST /supervision-sessions/{id}/approve | /reject).
    """
    return build_user_headers(counselor_id, "Supervisor")


def make_public_headers(visitor_id: str = "public-001") -> Dict[str, str]:
    """Public headers; identity is an opaque visitor id (PRD §2.1)."""
    return build_user_headers(visitor_id, "Public")


__all__ = [
    "TEST_USERS",
    "make_admin_headers",
    "make_crisis_responder_headers",
    "make_client_headers",
    "make_counselor_headers",
    "make_supervisor_headers",
    "make_public_headers",
]
