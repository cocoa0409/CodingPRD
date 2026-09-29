"""Caller identities.

The PRD splits identity semantics by role. For `ProgramAdmin`,
`PassOfficeClerk`, `GateAgent` and `ComplianceOfficer` the `X-User-ID` header is
an opaque operator identifier that the server never compares to an entity id, so
any stable string works. For `Passholder` the header value *is* the id of the
acting `Passholder` record, so headers for that role can only be built once the
passholder row exists — use :func:`make_passholder_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities. The values are arbitrary but stable so that
# segregation-of-duties comparisons in the PRD behave predictably.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": {"user_id": "admin-a1", "role": UserRole.PROGRAM_ADMIN.value},
    "pass_office_clerk": {"user_id": "clerk-c1", "role": UserRole.PASS_OFFICE_CLERK.value},
    "gate_agent": {"user_id": "gate-user-g1", "role": UserRole.GATE_AGENT.value},
    "compliance_officer": {"user_id": "officer-o1", "role": UserRole.COMPLIANCE_OFFICER.value},
}


def _headers(key: str) -> Dict[str, str]:
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def program_admin_headers() -> Dict[str, str]:
    """Headers for the season programme office."""
    return _headers("program_admin")


def clerk_headers() -> Dict[str, str]:
    """Headers for the pass office counter."""
    return _headers("pass_office_clerk")


def gate_agent_headers() -> Dict[str, str]:
    """Headers for the turnstile operator."""
    return _headers("gate_agent")


def compliance_officer_headers() -> Dict[str, str]:
    """Headers for the adjudicating compliance officer."""
    return _headers("compliance_officer")


def make_passholder_headers(passholder_id: str) -> Dict[str, str]:
    """Headers for a guest.

    The PRD states that when `X-User-Role` is `Passholder`, `X-User-ID` is the
    `id` of the acting `Passholder` record, so ownership checks compare a
    resource's `passholder_id` to this value. Every ownership-gated call must be
    made with the headers of the passholder that actually owns the resource.
    """
    return build_user_headers(passholder_id, UserRole.PASSHOLDER.value)


def make_gate_agent_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named gate agent.

    A sharing case records the opening agent's `X-User-ID`, so tests that later
    exercise the segregation-of-duties rule need control over the value.
    """
    return build_user_headers(user_id, UserRole.GATE_AGENT.value)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named compliance officer.

    The decide call compares the officer's `X-User-ID` with the case's
    `opened_by_user_id`, so tests need to pick the officer's identifier.
    """
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_program_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named programme administrator."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_clerk_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named pass office clerk."""
    return build_user_headers(user_id, UserRole.PASS_OFFICE_CLERK.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_with_undeclared_role(user_id: str = "someone-1") -> Dict[str, str]:
    """Headers naming a role the PRD does not declare."""
    return build_user_headers(user_id, "JanitorialStaff")


def headers_with_empty_user_id(role: str = UserRole.PROGRAM_ADMIN.value) -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but empty."""
    return build_user_headers("", role)
