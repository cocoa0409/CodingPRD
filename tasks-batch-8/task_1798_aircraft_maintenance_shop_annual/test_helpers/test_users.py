"""Pre-built role headers for every role in the PRD.

Roles ShopManager and PartsClerk are opaque: their X-User-ID is never compared
to an entity id, so a shared constant is canonical for them.

Roles Mechanic and Owner are entity-backed: whenever a call is ownership- or
identity-gated (e.g. discrepancy decisions, invoice payment, work-order start),
the headers MUST be built with the acting entity's actual id via the
make_*_headers builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "parts_clerk_headers": build_user_headers("test-parts-clerk-1", "PartsClerk"),
    # Entity-backed roles — shared constants are a fallback ONLY for tests whose
    # success does not depend on identity/ownership (e.g. 400/404 checks).
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
}


def make_mechanic_headers(user_id: str) -> dict:
    """For Mechanic (entity-backed: Mechanic). Pass the actual Mechanic.id as
    user_id whenever the call is identity-gated (labor posting, checklist record,
    verify, logbook signature, work-order lifecycle actions)."""
    return build_user_headers(user_id, "Mechanic")


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity-backed: Owner). Pass the actual Owner.id as user_id
    whenever the call is ownership-gated (discrepancy decide, reopen-inspection,
    invoice pay)."""
    return build_user_headers(user_id, "Owner")
