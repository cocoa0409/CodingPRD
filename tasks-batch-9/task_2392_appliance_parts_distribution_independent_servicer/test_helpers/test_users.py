"""Pre-built role headers for every role the PRD defines.

Two roles are entity-backed: for `Servicer` the `X-User-ID` must be the id of
the acting `ServicerAccount`, and for `BranchCounterRep` it must be the id of
the acting `Branch`.  Any ownership-gated call MUST therefore be made with the
matching per-instance builder below, never with the shared constant.

The remaining four roles are opaque operator identifiers that are never
compared against any entity id, so the shared constants are the canonical form
for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite.
CREDIT_MANAGER_USER_ONE = "cm-user-1"
CREDIT_MANAGER_USER_TWO = "cm-user-2"
WARRANTY_ADMIN_USER_ONE = "wa-user-1"
PRICING_ADMIN_USER_ONE = "pa-user-1"
PLATFORM_ADMIN_USER_ONE = "sa-user-1"


TEST_USERS = {
    # Entity-backed roles: shared constants are a fallback for calls that are
    # not ownership-gated (bad payloads, missing resources, role checks).
    "servicer_headers": build_user_headers("test-servicer-1", "Servicer"),
    "branch_counter_rep_headers": build_user_headers(
        "test-branch-rep-1", "BranchCounterRep"
    ),
    # Opaque roles: shared constants are the canonical form.
    "credit_manager_headers": build_user_headers(
        CREDIT_MANAGER_USER_ONE, "CreditManager"
    ),
    "credit_manager_two_headers": build_user_headers(
        CREDIT_MANAGER_USER_TWO, "CreditManager"
    ),
    "warranty_admin_headers": build_user_headers(
        WARRANTY_ADMIN_USER_ONE, "WarrantyAdmin"
    ),
    "pricing_admin_headers": build_user_headers(
        PRICING_ADMIN_USER_ONE, "PricingAdmin"
    ),
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ONE, "PlatformAdmin"
    ),
}


# --- Per-instance builders ------------------------------------------------

def make_servicer_headers(servicer_account_id: str) -> dict:
    """Headers for a `Servicer` acting as the given `ServicerAccount`."""
    return build_user_headers(servicer_account_id, "Servicer")


def make_branch_counter_rep_headers(branch_id: str) -> dict:
    """Headers for a `BranchCounterRep` acting as the given `Branch`."""
    return build_user_headers(branch_id, "BranchCounterRep")


def make_credit_manager_headers(user_id: str) -> dict:
    """Headers for a `CreditManager` acting under a specific operator id."""
    return build_user_headers(user_id, "CreditManager")


def make_warranty_admin_headers(user_id: str) -> dict:
    """Headers for a `WarrantyAdmin` acting under a specific operator id."""
    return build_user_headers(user_id, "WarrantyAdmin")


def make_pricing_admin_headers(user_id: str) -> dict:
    """Headers for a `PricingAdmin` acting under a specific operator id."""
    return build_user_headers(user_id, "PricingAdmin")


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a `PlatformAdmin` acting under a specific operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


# Frequently used shorthands.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
PRICING_ADMIN = TEST_USERS["pricing_admin_headers"]
CREDIT_MANAGER = TEST_USERS["credit_manager_headers"]
CREDIT_MANAGER_TWO = TEST_USERS["credit_manager_two_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
