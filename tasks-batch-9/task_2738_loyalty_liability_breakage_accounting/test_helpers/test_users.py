"""
The acting identities every test sends.

Three roles are opaque operators: their ``X-User-ID`` is never compared with any
entity's ``id``, so each gets one stable module-level identity. Two roles are
entity-backed: a ``PartnerOperator`` acts as the partner agreement whose ``id``
it carries, and a ``Member`` acts as the member whose ``id`` it carries, so their
headers can only be built once the entity exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.constants import (
    ROLE_CONTROLLER,
    ROLE_LOYALTY_ACCOUNTANT,
    ROLE_MEMBER,
    ROLE_PARTNER_OPERATOR,
    ROLE_PROGRAM_ADMIN,
)

# ─── Opaque operator identities ──────────────────────────────────────────────
PROGRAM_ADMIN_ID = "user-program-admin-1"
ACCOUNTANT_ID = "user-accountant-1"
ACCOUNTANT_2_ID = "user-accountant-2"
CONTROLLER_ID = "user-controller-1"
CONTROLLER_2_ID = "user-controller-2"

PROGRAM_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN
)
ACCOUNTANT_HEADERS: Dict[str, str] = build_user_headers(
    ACCOUNTANT_ID, ROLE_LOYALTY_ACCOUNTANT
)
ACCOUNTANT_2_HEADERS: Dict[str, str] = build_user_headers(
    ACCOUNTANT_2_ID, ROLE_LOYALTY_ACCOUNTANT
)
CONTROLLER_HEADERS: Dict[str, str] = build_user_headers(CONTROLLER_ID, ROLE_CONTROLLER)
CONTROLLER_2_HEADERS: Dict[str, str] = build_user_headers(
    CONTROLLER_2_ID, ROLE_CONTROLLER
)

# The one identity that is a Controller *and* the same human as the preparer,
# for the segregation-of-duties probe.
PREPARER_AS_CONTROLLER_HEADERS: Dict[str, str] = build_user_headers(
    ACCOUNTANT_ID, ROLE_CONTROLLER
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_HEADERS,
    ROLE_LOYALTY_ACCOUNTANT: ACCOUNTANT_HEADERS,
    ROLE_CONTROLLER: CONTROLLER_HEADERS,
}


# ─── Entity-backed identities ────────────────────────────────────────────────
def make_partner_operator_headers(partner_agreement_id: str) -> Dict[str, str]:
    """Headers for a PartnerOperator acting as one partner agreement."""
    return build_user_headers(partner_agreement_id, ROLE_PARTNER_OPERATOR)


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for a Member acting on its own account."""
    return build_user_headers(member_id, ROLE_MEMBER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role and acting identity."""
    return build_user_headers(user_id, role)


# ─── Malformed identities ────────────────────────────────────────────────────
def make_unknown_role_headers(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
    """A well-formed identity declaring a role the contract does not recognise."""
    return build_user_headers(user_id, "LoyaltyOverlord")


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PROGRAM_ADMIN_ID,
    "Content-Type": "application/json",
}

MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_PROGRAM_ADMIN,
    "Content-Type": "application/json",
}

EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PROGRAM_ADMIN,
    "Content-Type": "application/json",
}

EMPTY_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PROGRAM_ADMIN_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
