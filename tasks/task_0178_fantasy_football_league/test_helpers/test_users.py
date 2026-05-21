"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

OPAQUE roles — X-User-ID is an opaque operator identifier that the
server records but never compares to any persisted entity id:
  - Commissioner — PRD §2.1: "When X-User-Role is Commissioner,
    X-User-ID is an opaque operator identifier that is not tied to any
    persisted entity; the server may accept and record it but never
    compares it to any entity's id." Shared constants are canonical.

ENTITY-BACKED roles — PRD §2.1: "When X-User-Role is Manager, X-User-ID
is the value stored in Team.manager_user_id for the acting franchise;
ownership-gated actions resolve the acting Manager's team_id by looking
up the Team whose manager_user_id equals X-User-ID."

  - Manager — every ownership-gated call MUST mint headers via
    make_manager_headers(manager_user_id) using the actual
    Team.manager_user_id of the team the call targets. Falling back to
    the shared constant would cause "operation that targets a team_id
    other than the one the acting Manager owns is rejected with
    ERR_NOT_TEAM_OWNER" to fire on every owned call.

The MANAGER_FALLBACK_ID below is reserved for tests that do NOT
exercise ownership (missing-headers / role-mismatch / NotFound paths
or calls where the role is provably non-permitted regardless of the
identity).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids — PRD §2.1 says the server records but never
# compares Commissioner X-User-ID to any entity id, so a shared constant
# is contract-correct.
# ---------------------------------------------------------------------------
COMMISSIONER_ID = "commissioner-1"
COMMISSIONER_ID_ALT = "commissioner-2"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback id — DO NOT USE for ownership-gated calls.
# Use make_manager_headers(manager_user_id) with the actual
# Team.manager_user_id minted at team creation.
# ---------------------------------------------------------------------------
MANAGER_FALLBACK_ID = "manager-fallback-uid"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — shared constant canonical (PRD §2.1).
    "commissioner_headers": build_user_headers(COMMISSIONER_ID, "Commissioner"),
    "commissioner_headers_alt": build_user_headers(
        COMMISSIONER_ID_ALT, "Commissioner",
    ),

    # Entity-backed fallback — safe only for non-ownership tests.
    "manager_headers": build_user_headers(MANAGER_FALLBACK_ID, "Manager"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for Manager whenever the call is
# ownership-gated. The id passed in must equal the target team's
# manager_user_id (the value stored in Team.manager_user_id when the
# Team row was created).
# ---------------------------------------------------------------------------
def make_manager_headers(manager_user_id: str) -> Dict[str, str]:
    """For Manager (entity_backed:Team). Pass the manager_user_id of the
    target team — PRD §2.1: "ownership-gated actions resolve the acting
    Manager's team_id by looking up the Team whose manager_user_id
    equals X-User-ID, and any operation that targets a team_id other
    than the one the acting Manager owns is rejected with
    ERR_NOT_TEAM_OWNER."
    """
    return build_user_headers(manager_user_id, "Manager")


def make_commissioner_headers(commissioner_id: str) -> Dict[str, str]:
    """For Commissioner (opaque). The id is recorded but not compared
    to any entity per PRD §2.1."""
    return build_user_headers(commissioner_id, "Commissioner")


__all__ = [
    "COMMISSIONER_ID",
    "COMMISSIONER_ID_ALT",
    "MANAGER_FALLBACK_ID",
    "TEST_USERS",
    "make_manager_headers",
    "make_commissioner_headers",
]
