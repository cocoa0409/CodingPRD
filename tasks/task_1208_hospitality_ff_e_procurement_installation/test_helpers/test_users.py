"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an opaque operator identity: X-User-ID is not the id of any
persisted entity. The single place an operator identity is persisted is the
change-order workflow (proposer_user_id + segregation of duties), so every role
also gets a per-user-id builder for tests that must control X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "purchasing_agent_headers": build_user_headers("test-pa-1", "PurchasingAgent"),
    "brand_approver_headers": build_user_headers("test-ba-1", "BrandApprover"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    "warehouse_receiver_headers": build_user_headers("test-wr-1", "WarehouseReceiver"),
    "installation_manager_headers": build_user_headers(
        "test-im-1", "InstallationManager"
    ),
    "owner_rep_headers": build_user_headers("test-owner-1", "OwnerRep"),
}


def make_purchasing_agent_headers(user_id: str) -> dict:
    """PurchasingAgent headers with a specific X-User-ID (e.g. change-order
    proposer identity for segregation-of-duties tests)."""
    return build_user_headers(user_id, "PurchasingAgent")


def make_brand_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BrandApprover")


def make_vendor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Vendor")


def make_warehouse_receiver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseReceiver")


def make_installation_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InstallationManager")


def make_owner_rep_headers(user_id: str) -> dict:
    """OwnerRep headers with a specific X-User-ID (change-order decisions are
    forbidden for the proposer's own user id)."""
    return build_user_headers(user_id, "OwnerRep")
