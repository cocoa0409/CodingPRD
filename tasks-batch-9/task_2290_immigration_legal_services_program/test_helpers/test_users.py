"""Identity header builders for the six declared roles.

Four of the six roles are *entity backed*: the ``X-User-ID`` the caller sends
must be the primary key of a row that already exists, because the contract
resolves it to decide ownership, segregation of duties and case membership.

  IntakeScreener        -> Representative.id   (becomes screener_representative_id)
  SupervisingAttorney   -> Representative.id   (becomes decided_by / approver id)
  CaseRepresentative    -> Representative.id   (must sit on the matter)
  ClientPortalUser      -> Client.id           (row scoped to its own client)

The remaining two are opaque program-level identities whose ``X-User-ID`` is
never resolved against any collection:

  ProgramDirector       -> opaque
  GrantAnalyst          -> opaque

Passing a shared constant where a real row id is required is the canonical bug
these builders exist to prevent, so every entity-backed builder demands the id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CASE_REPRESENTATIVE,
    ROLE_CLIENT_PORTAL_USER,
    ROLE_GRANT_ANALYST,
    ROLE_INTAKE_SCREENER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SUPERVISING_ATTORNEY,
)

# ---------------------------------------------------------------------------
# Opaque identities: stable across a whole test run.
# ---------------------------------------------------------------------------
PROGRAM_DIRECTOR_ID = "director-001"
GRANT_ANALYST_ID = "analyst-001"

PROGRAM_DIRECTOR_HEADERS: Dict[str, str] = build_user_headers(
    PROGRAM_DIRECTOR_ID, ROLE_PROGRAM_DIRECTOR
)
GRANT_ANALYST_HEADERS: Dict[str, str] = build_user_headers(
    GRANT_ANALYST_ID, ROLE_GRANT_ANALYST
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_DIRECTOR: PROGRAM_DIRECTOR_HEADERS,
    ROLE_GRANT_ANALYST: GRANT_ANALYST_HEADERS,
}


def program_director_headers() -> Dict[str, str]:
    """Headers for the opaque ProgramDirector identity."""
    return dict(PROGRAM_DIRECTOR_HEADERS)


def grant_analyst_headers() -> Dict[str, str]:
    """Headers for the opaque GrantAnalyst identity."""
    return dict(GRANT_ANALYST_HEADERS)


def _require(entity_id: str, role: str) -> str:
    if not entity_id:
        raise ValueError(
            "{0} is an entity-backed role: pass the real row id, never a "
            "shared placeholder".format(role)
        )
    return entity_id


def make_intake_screener_headers(representative_id: str) -> Dict[str, str]:
    """IntakeScreener acting as a concrete Representative row."""
    return build_user_headers(
        _require(representative_id, ROLE_INTAKE_SCREENER), ROLE_INTAKE_SCREENER
    )


def make_supervising_attorney_headers(representative_id: str) -> Dict[str, str]:
    """SupervisingAttorney acting as a concrete Representative row."""
    return build_user_headers(
        _require(representative_id, ROLE_SUPERVISING_ATTORNEY),
        ROLE_SUPERVISING_ATTORNEY,
    )


def make_case_representative_headers(representative_id: str) -> Dict[str, str]:
    """CaseRepresentative acting as a concrete Representative row."""
    return build_user_headers(
        _require(representative_id, ROLE_CASE_REPRESENTATIVE), ROLE_CASE_REPRESENTATIVE
    )


def make_client_portal_headers(client_id: str) -> Dict[str, str]:
    """ClientPortalUser acting as a concrete Client row."""
    return build_user_headers(
        _require(client_id, ROLE_CLIENT_PORTAL_USER), ROLE_CLIENT_PORTAL_USER
    )


def make_headers(role: str, entity_id: str = "") -> Dict[str, str]:
    """Generic dispatcher used by role-sweep tests.

    Opaque roles ignore ``entity_id``; entity-backed roles require it.
    """
    if role == ROLE_PROGRAM_DIRECTOR:
        return program_director_headers()
    if role == ROLE_GRANT_ANALYST:
        return grant_analyst_headers()
    if role == ROLE_INTAKE_SCREENER:
        return make_intake_screener_headers(entity_id)
    if role == ROLE_SUPERVISING_ATTORNEY:
        return make_supervising_attorney_headers(entity_id)
    if role == ROLE_CASE_REPRESENTATIVE:
        return make_case_representative_headers(entity_id)
    if role == ROLE_CLIENT_PORTAL_USER:
        return make_client_portal_headers(entity_id)
    raise ValueError("unknown role {0!r}".format(role))
