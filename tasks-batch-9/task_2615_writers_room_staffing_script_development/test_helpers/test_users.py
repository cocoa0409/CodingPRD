"""Identity headers for the five roles of the contract.

Two of the roles are entity-backed: an acting Showrunner or Writer must present
the id of a real Writer row, so those two roles get per-instance builders that
thread a freshly created writer id. The three opaque roles (StudioExecutive,
GuildAdministrator, LegalCounsel) get one shared identity each.
"""

import uuid
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Shared opaque identities ------------------------------------------------

STUDIO_EXECUTIVE_USER_ID = "11111111-1111-4111-8111-111111111111"
GUILD_ADMINISTRATOR_USER_ID = "22222222-2222-4222-8222-222222222222"
LEGAL_COUNSEL_USER_ID = "33333333-3333-4333-8333-333333333333"

# A syntactically valid id that belongs to no Writer row, for the acting-writer
# resolution checks.
UNKNOWN_WRITER_USER_ID = "44444444-4444-4444-8444-444444444444"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "studio_executive": build_user_headers(
        STUDIO_EXECUTIVE_USER_ID, UserRole.STUDIO_EXECUTIVE.value
    ),
    "guild_administrator": build_user_headers(
        GUILD_ADMINISTRATOR_USER_ID, UserRole.GUILD_ADMINISTRATOR.value
    ),
    "legal_counsel": build_user_headers(
        LEGAL_COUNSEL_USER_ID, UserRole.LEGAL_COUNSEL.value
    ),
    # Placeholder identities for the entity-backed roles. Any call that is
    # ownership-gated or season-showrunner-gated must instead use the builders
    # below with a real Writer id.
    "showrunner": build_user_headers(
        UNKNOWN_WRITER_USER_ID, UserRole.SHOWRUNNER.value
    ),
    "writer": build_user_headers(UNKNOWN_WRITER_USER_ID, UserRole.WRITER.value),
}

STUDIO_EXECUTIVE_HEADERS = TEST_USERS["studio_executive"]
GUILD_ADMINISTRATOR_HEADERS = TEST_USERS["guild_administrator"]
LEGAL_COUNSEL_HEADERS = TEST_USERS["legal_counsel"]


# --- Entity-backed identity builders -----------------------------------------

def make_writer_headers(user_id: str) -> Dict[str, str]:
    """Headers for the Writer role acting as the Writer row `user_id`."""
    return build_user_headers(user_id, UserRole.WRITER.value)


def make_showrunner_headers(user_id: str) -> Dict[str, str]:
    """Headers for the Showrunner role acting as the Writer row `user_id`."""
    return build_user_headers(user_id, UserRole.SHOWRUNNER.value)


def make_studio_executive_headers(
    user_id: str = STUDIO_EXECUTIVE_USER_ID,
) -> Dict[str, str]:
    """Headers for the opaque StudioExecutive role."""
    return build_user_headers(user_id, UserRole.STUDIO_EXECUTIVE.value)


def make_guild_administrator_headers(
    user_id: str = GUILD_ADMINISTRATOR_USER_ID,
) -> Dict[str, str]:
    """Headers for the opaque GuildAdministrator role."""
    return build_user_headers(user_id, UserRole.GUILD_ADMINISTRATOR.value)


def make_legal_counsel_headers(
    user_id: str = LEGAL_COUNSEL_USER_ID,
) -> Dict[str, str]:
    """Headers for the opaque LegalCounsel role."""
    return build_user_headers(user_id, UserRole.LEGAL_COUNSEL.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/id pair."""
    return build_user_headers(user_id, role)


def headers_with_unknown_role(user_id: str = STUDIO_EXECUTIVE_USER_ID) -> Dict[str, str]:
    """Headers naming a role that is not in the contract's role vocabulary."""
    return build_user_headers(user_id, "ScriptCoordinator")


def headers_missing_user_id(role: str = UserRole.STUDIO_EXECUTIVE.value):
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = STUDIO_EXECUTIVE_USER_ID):
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = UserRole.STUDIO_EXECUTIVE.value):
    """Headers whose X-User-ID is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_empty_role(user_id: str = STUDIO_EXECUTIVE_USER_ID):
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def fresh_uuid() -> str:
    """A syntactically valid identifier that names no row."""
    return str(uuid.uuid4())


ALL_ROLE_NAMES = [role.value for role in UserRole]
OPAQUE_ROLE_NAMES = [
    UserRole.STUDIO_EXECUTIVE.value,
    UserRole.GUILD_ADMINISTRATOR.value,
    UserRole.LEGAL_COUNSEL.value,
]
ENTITY_BACKED_ROLE_NAMES = [UserRole.SHOWRUNNER.value, UserRole.WRITER.value]
