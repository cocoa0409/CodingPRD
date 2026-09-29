"""Test actor headers for the five roles the PRD declares.

Every request must carry `X-User-ID`, identifying the actor, and
`X-User-Role`, naming the capacity the actor is acting in.

Identity resolution differs by role. For `ChiefPerfusionist` and
`Perfusionist`, `X-User-ID` is the `id` of the acting `Perfusionist` row; for
`Surgeon` it is the `id` of the acting `Surgeon` row, and an `X-User-ID` that
does not resolve to an existing row of the backing entity is rejected. For
`ContractAdmin` and `BiomedTech`, `X-User-ID` is an opaque operator identifier
not tied to any persisted entity, so a literal string is always acceptable.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identifiers ──────────────────────
# These two roles are never resolved against a table, so any stable string
# works for the whole suite.
CONTRACT_ADMIN_USER_ID = "admin-op-0001"
BIOMED_TECH_USER_ID = "tech-op-0001"

# The entity-backed roles have no fixed identifier: the acting row's `id` is
# only known once the row has been created, so the placeholder below is used
# solely to make the shared registry uniform. Tests that exercise ownership
# always pass a real `id` through the builders further down.
UNRESOLVED_ACTOR_ID = "00000000-0000-4000-8000-000000000000"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ContractAdmin": {
        "user_id": CONTRACT_ADMIN_USER_ID,
        "role": "ContractAdmin",
    },
    "ChiefPerfusionist": {
        "user_id": UNRESOLVED_ACTOR_ID,
        "role": "ChiefPerfusionist",
    },
    "Perfusionist": {
        "user_id": UNRESOLVED_ACTOR_ID,
        "role": "Perfusionist",
    },
    "BiomedTech": {
        "user_id": BIOMED_TECH_USER_ID,
        "role": "BiomedTech",
    },
    "Surgeon": {
        "user_id": UNRESOLVED_ACTOR_ID,
        "role": "Surgeon",
    },
}


# ─── Opaque-role header builders ──────────────────────
def make_contract_admin_headers(user_id: str = CONTRACT_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the commercial and credentialing back office."""
    return build_user_headers(user_id, "ContractAdmin")


def make_biomed_tech_headers(user_id: str = BIOMED_TECH_USER_ID) -> Dict[str, str]:
    """Headers for the biomedical engineering technician."""
    return build_user_headers(user_id, "BiomedTech")


# ─── Entity-backed header builders ────────────────────
def make_chief_perfusionist_headers(user_id: str) -> Dict[str, str]:
    """Headers for a senior perfusionist; `user_id` is the acting Perfusionist's id.

    The chief capacity is a property of the person, not a claim the header can
    make on its own, so the row must have `is_chief` set to true.
    """
    return build_user_headers(user_id, "ChiefPerfusionist")


def make_perfusionist_headers(user_id: str) -> Dict[str, str]:
    """Headers for a staff perfusionist; `user_id` is the acting Perfusionist's id."""
    return build_user_headers(user_id, "Perfusionist")


def make_surgeon_headers(user_id: str) -> Dict[str, str]:
    """Headers for an operating surgeon; `user_id` is the acting Surgeon's id."""
    return build_user_headers(user_id, "Surgeon")


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for any of the five roles, with an explicit actor identifier."""
    return build_user_headers(user_id, role)


def make_headers_for_role(role: str) -> Dict[str, str]:
    """Headers built from the shared registry, for role-only checks."""
    entry = TEST_USERS[role]
    return build_user_headers(entry["user_id"], entry["role"])


NO_AUTH_HEADERS: Dict[str, str] = {}
