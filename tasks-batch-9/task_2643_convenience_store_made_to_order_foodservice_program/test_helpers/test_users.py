"""Pre-built auth headers, one per role, plus per-actor builders.

Six of the seven roles are opaque: the caller identity is an arbitrary
non-blank string and the API only reads the role. ``Customer`` is different —
its ``X-User-ID`` must equal the id of the loyalty account that owns the order
being touched, so customer headers are always built per-account with
:func:`make_customer_headers`.

Segregation-of-duties rules compare two recorded actor ids, so tests that
exercise them need two or more *distinct* ids inside the same opaque role.
The named actor constants below exist for that purpose.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Named actors (distinct ids inside one role) ──────────────────────
CHAIN_ADMIN_USER_ID = "admin-1"
STORE_MANAGER_USER_ID = "sm-1"
ASSOCIATE_1_USER_ID = "assoc-1"
ASSOCIATE_2_USER_ID = "assoc-2"
SHIFT_LEAD_1_USER_ID = "lead-1"
SHIFT_LEAD_2_USER_ID = "lead-2"
SHIFT_LEAD_9_USER_ID = "lead-9"
FOOD_SAFETY_LEAD_USER_ID = "fsl-1"
TERMINAL_USER_ID = "term-1"
UNKNOWN_USER_ID = "u-7"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build auth headers for an arbitrary actor id and role."""
    return build_user_headers(user_id, role)


def make_customer_headers(loyalty_account_id: str) -> Dict[str, str]:
    """Customer headers for the member who owns the resource under test.

    The Customer role is entity-backed: the caller id must be the owning
    loyalty account's id, otherwise ownership-scoped operations are refused.
    """
    return build_user_headers(loyalty_account_id, UserRole.CUSTOMER.value)


def make_associate_headers(user_id: str = ASSOCIATE_1_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.KITCHEN_ASSOCIATE.value)


def make_shift_lead_headers(user_id: str = SHIFT_LEAD_1_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SHIFT_LEAD.value)


def make_food_safety_lead_headers(user_id: str = FOOD_SAFETY_LEAD_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FOOD_SAFETY_LEAD.value)


# ─── Ready-made headers, one per role ─────────────────────────────────
CHAIN_ADMIN_HEADERS = build_user_headers(CHAIN_ADMIN_USER_ID, UserRole.CHAIN_ADMIN.value)
STORE_MANAGER_HEADERS = build_user_headers(STORE_MANAGER_USER_ID, UserRole.STORE_MANAGER.value)
KITCHEN_ASSOCIATE_HEADERS = build_user_headers(
    ASSOCIATE_1_USER_ID, UserRole.KITCHEN_ASSOCIATE.value
)
KITCHEN_ASSOCIATE_2_HEADERS = build_user_headers(
    ASSOCIATE_2_USER_ID, UserRole.KITCHEN_ASSOCIATE.value
)
SHIFT_LEAD_HEADERS = build_user_headers(SHIFT_LEAD_1_USER_ID, UserRole.SHIFT_LEAD.value)
SHIFT_LEAD_2_HEADERS = build_user_headers(SHIFT_LEAD_2_USER_ID, UserRole.SHIFT_LEAD.value)
FOOD_SAFETY_LEAD_HEADERS = build_user_headers(
    FOOD_SAFETY_LEAD_USER_ID, UserRole.FOOD_SAFETY_LEAD.value
)
STORE_TERMINAL_HEADERS = build_user_headers(TERMINAL_USER_ID, UserRole.STORE_TERMINAL.value)

# Headers whose role string is not one of the seven recognised roles.
UNRECOGNISED_ROLE_HEADERS = {
    "X-User-ID": UNKNOWN_USER_ID,
    "X-User-Role": "RegionalDirector",
    "Content-Type": "application/json",
}

# Headers with no caller identity at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

BLANK_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": UserRole.CHAIN_ADMIN.value,
    "Content-Type": "application/json",
}

TEST_USERS: Dict[str, Dict[str, str]] = {
    "chain_admin": CHAIN_ADMIN_HEADERS,
    "store_manager": STORE_MANAGER_HEADERS,
    "kitchen_associate": KITCHEN_ASSOCIATE_HEADERS,
    "shift_lead": SHIFT_LEAD_HEADERS,
    "food_safety_lead": FOOD_SAFETY_LEAD_HEADERS,
    "store_terminal": STORE_TERMINAL_HEADERS,
}
