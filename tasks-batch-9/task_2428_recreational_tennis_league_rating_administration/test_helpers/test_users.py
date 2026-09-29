"""Actor identities and header builders (PRD 2.1).

Two of the six roles are opaque (``SectionAdmin``, ``LeagueCoordinator``): their
``X-User-ID`` never has to resolve to a Player row, so a fixed placeholder id is
fine and the ready-made header dicts below are safe to share across tests.

The other four roles (``Captain``, ``Player``, ``CommitteeMember``,
``CommitteeChair``) are entity-backed by ``Player``.  For those roles the acting
identity is load-bearing — ownership, self-scoping and segregation-of-duties
checks all read ``X-User-ID`` — so tests MUST build headers per acting player id
with the ``make_*_headers`` builders and must never reuse a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CAPTAIN,
    ROLE_COMMITTEE_CHAIR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_LEAGUE_COORDINATOR,
    ROLE_PLAYER,
    ROLE_SECTION_ADMIN,
)

# Opaque-role placeholder identities -----------------------------------------
OPAQUE_ADMIN_USER_ID = "section-admin-1"
OPAQUE_COORDINATOR_USER_ID = "league-coordinator-1"

SECTION_ADMIN = build_user_headers(OPAQUE_ADMIN_USER_ID, ROLE_SECTION_ADMIN)
LEAGUE_COORDINATOR = build_user_headers(
    OPAQUE_COORDINATOR_USER_ID, ROLE_LEAGUE_COORDINATOR
)


# Entity-backed role builders -------------------------------------------------
def make_captain_headers(player_id: str) -> Dict[str, str]:
    """Headers for the Captain role backed by ``player_id``."""
    return build_user_headers(player_id, ROLE_CAPTAIN)


def make_player_headers(player_id: str) -> Dict[str, str]:
    """Headers for the Player role backed by ``player_id``."""
    return build_user_headers(player_id, ROLE_PLAYER)


def make_committee_member_headers(player_id: str) -> Dict[str, str]:
    """Headers for the CommitteeMember role backed by ``player_id``."""
    return build_user_headers(player_id, ROLE_COMMITTEE_MEMBER)


def make_committee_chair_headers(player_id: str) -> Dict[str, str]:
    """Headers for the CommitteeChair role backed by ``player_id``."""
    return build_user_headers(player_id, ROLE_COMMITTEE_CHAIR)


def make_role_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role string — used by RBAC probes."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Auth headers with ``X-User-Role`` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Auth headers with ``X-User-ID`` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
