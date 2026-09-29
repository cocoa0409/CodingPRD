"""Pre-built role headers for the seven roles named in the PRD.

PlatformAdmin, PricingAnalyst, PricingManager, ComplianceOfficer and
DataCollector present an opaque operator identifier in X-User-ID.
StoreAssociate and StoreManager present the id of the acting Store, so
ownership-gated calls MUST use the per-store builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "pricing_analyst_headers": build_user_headers("analyst-1", "PricingAnalyst"),
    "pricing_manager_headers": build_user_headers("manager-9", "PricingManager"),
    "compliance_officer_headers": build_user_headers("compliance-3", "ComplianceOfficer"),
    "data_collector_headers": build_user_headers("collector-5", "DataCollector"),
    # Store roles: these shared constants are safe only for calls that are not
    # store-ownership gated (unknown-role checks, 404 probes and the like).
    "store_associate_headers": build_user_headers("associate-1", "StoreAssociate"),
    "store_manager_headers": build_user_headers("manager-1", "StoreManager"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_pricing_analyst_headers(user_id: str = "analyst-1") -> dict:
    return build_user_headers(user_id, "PricingAnalyst")


def make_pricing_manager_headers(user_id: str = "manager-9") -> dict:
    return build_user_headers(user_id, "PricingManager")


def make_compliance_officer_headers(user_id: str = "compliance-3") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_data_collector_headers(user_id: str = "collector-5") -> dict:
    return build_user_headers(user_id, "DataCollector")


def make_store_associate_headers(store_id: str) -> dict:
    """StoreAssociate acts for one store: pass that Store's id as X-User-ID."""
    return build_user_headers(store_id, "StoreAssociate")


def make_store_manager_headers(store_id: str) -> dict:
    """StoreManager acts for one store: pass that Store's id as X-User-ID."""
    return build_user_headers(store_id, "StoreManager")


ALL_ROLE_NAMES = [
    "PlatformAdmin",
    "PricingAnalyst",
    "PricingManager",
    "ComplianceOfficer",
    "DataCollector",
    "StoreAssociate",
    "StoreManager",
]
