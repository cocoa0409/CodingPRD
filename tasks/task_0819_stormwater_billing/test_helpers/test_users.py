"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque staff roles (Assessor, BillingClerk,
# CreditInspector, StormwaterAdmin), whose X-User-ID is never compared to any
# entity id (PRD §2.1), and for tests that do not exercise PropertyOwner ownership.
TEST_USERS = {
    # PropertyOwner is entity_backed:Account — this shared constant is only a
    # fallback for non-ownership tests. Ownership-gated calls MUST use
    # make_property_owner_headers(account_id) instead.
    "property_owner_headers": build_user_headers("test-owner-1", "PropertyOwner"),
    "assessor_headers": build_user_headers("test-assessor-1", "Assessor"),
    "billing_clerk_headers": build_user_headers("test-clerk-1", "BillingClerk"),
    "credit_inspector_headers": build_user_headers("test-inspector-1", "CreditInspector"),
    "stormwater_admin_headers": build_user_headers("test-admin-1", "StormwaterAdmin"),
}


# --- Per-instance builders ---

def make_property_owner_headers(account_id: str) -> dict:
    """For PropertyOwner (entity_backed:Account). Pass the acting Account.id as
    X-User-ID whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(account_id, "PropertyOwner")


def make_assessor_headers(user_id: str = "test-assessor-1") -> dict:
    return build_user_headers(user_id, "Assessor")


def make_billing_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """For BillingClerk (opaque). Pass a distinct user_id to control
    created_by_user_id for segregation-of-duties tests (PRD §3.6)."""
    return build_user_headers(user_id, "BillingClerk")


def make_credit_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "CreditInspector")


def make_stormwater_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "StormwaterAdmin")
