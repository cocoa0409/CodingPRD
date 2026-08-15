"""Pre-built role headers for every role in the PRD.

Opaque roles (ProgramAdmin, MarketManager, BoothOperator, Auditor) use shared
constants: their X-User-ID is never compared to a stored entity. Vendor and
Shopper are entity-backed: ownership-gated calls MUST use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "market_manager_headers": build_user_headers("test-manager-1", "MarketManager"),
    "booth_operator_headers": build_user_headers("test-booth-1", "BoothOperator"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Entity-backed roles — fallback only for tests that do NOT exercise ownership
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    "shopper_headers": build_user_headers("test-shopper-1", "Shopper"),
}


def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed: pass the actual Vendor.id as user_id whenever
    the call is ownership-gated (redeem, reverse-redemption, claim create/resubmit,
    reading the vendor's own record)."""
    return build_user_headers(user_id, "Vendor")


def make_shopper_headers(user_id: str) -> dict:
    """Shopper is entity-backed: pass the actual Shopper.id as user_id whenever
    the call reads the shopper's own record."""
    return build_user_headers(user_id, "Shopper")
