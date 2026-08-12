"""Pre-built role headers for every role the PRD declares.

Three roles are backed by a persisted Account and their ``X-User-ID`` is that
account's ``id``: AccountHolder, RegistryOwner and GiftPurchaser.  For those
roles ALWAYS use the per-instance builder with the real account id — a shared
constant would never equal a real account and every ownership check would
refuse the request.

The remaining three roles (Anonymous, SupportAgent, OpsAdmin) carry opaque
identifiers that the server never compares against an entity id, so the shared
constants below are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- opaque identities ----------------------------------------------------
ANON_USER_ID = "anon-visitor-1"
SUPPORT_AGENT_ID = "cs-1"
SUPPORT_AGENT_2_ID = "cs-2"
OPS_ADMIN_ID = "ops-1"
OPS_ADMIN_2_ID = "ops-2"

TEST_USERS = {
    "anonymous_headers": build_user_headers(ANON_USER_ID, "Anonymous"),
    "support_agent_headers": build_user_headers(SUPPORT_AGENT_ID, "SupportAgent"),
    "support_agent_2_headers": build_user_headers(SUPPORT_AGENT_2_ID, "SupportAgent"),
    "ops_admin_headers": build_user_headers(OPS_ADMIN_ID, "OpsAdmin"),
    "ops_admin_2_headers": build_user_headers(OPS_ADMIN_2_ID, "OpsAdmin"),
    # Fallbacks for entity-backed roles: use ONLY where ownership is not
    # exercised (missing-resource 404s, malformed-body 400s).
    "account_holder_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "AccountHolder"
    ),
    "registry_owner_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "RegistryOwner"
    ),
    "gift_purchaser_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "GiftPurchaser"
    ),
}

# A syntactically valid UUID that no resource ever uses.
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"


# --- per-instance builders for the entity-backed roles --------------------
def make_account_holder_headers(account_id: str) -> dict:
    """AccountHolder acting as the household whose Account.id is account_id."""
    return build_user_headers(account_id, "AccountHolder")


def make_registry_owner_headers(account_id: str) -> dict:
    """RegistryOwner acting as the Account that owns the addressed registry."""
    return build_user_headers(account_id, "RegistryOwner")


def make_gift_purchaser_headers(account_id: str) -> dict:
    """GiftPurchaser acting as the Account named on the gift order."""
    return build_user_headers(account_id, "GiftPurchaser")


def make_support_agent_headers(user_id: str = SUPPORT_AGENT_ID) -> dict:
    return build_user_headers(user_id, "SupportAgent")


def make_ops_admin_headers(user_id: str = OPS_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_anonymous_headers(user_id: str = ANON_USER_ID) -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_raw_headers(user_id=None, role=None) -> dict:
    """Header dict with either component deliberately omitted.

    Used by the authentication tests, which must send a request with no
    ``X-User-Role`` at all rather than an empty one.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers
