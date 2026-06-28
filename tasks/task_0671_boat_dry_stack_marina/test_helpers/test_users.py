"""Pre-built role headers for every role in the PRD (§2.1).

DockMaster and BillingClerk carry an opaque X-User-ID that is never compared to
any entity id, so a shared constant is the canonical form for them. BoatOwner is
entity_backed:BoatOwnerAccount — its X-User-ID must equal the acting owner
account id, so ownership-gated calls MUST use make_boat_owner_headers(owner_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   DockMaster / BillingClerk: opaque identity, shared constant is canonical.
#   BoatOwner: shared constant is a non-ownership fallback ONLY (e.g. 401/403/404
#   negative tests). Ownership-gated BoatOwner calls use make_boat_owner_headers.
TEST_USERS = {
    "dock_master_headers": build_user_headers("test-dockmaster-1", "DockMaster"),
    "billing_clerk_headers": build_user_headers("test-billingclerk-1", "BillingClerk"),
    "boat_owner_headers": build_user_headers("test-boatowner-1", "BoatOwner"),
}


def make_boat_owner_headers(owner_id: str) -> dict:
    """For BoatOwner (entity_backed:BoatOwnerAccount). Pass the actual
    BoatOwnerAccount.id as owner_id whenever the call is ownership-gated
    (mutating a vessel / launch / service order / invoice owned by that account)."""
    return build_user_headers(owner_id, "BoatOwner")
