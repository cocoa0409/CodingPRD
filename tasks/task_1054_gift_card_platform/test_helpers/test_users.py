"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are opaque (PlatformAdmin, POSTerminal, FraudAnalyst,
SettlementOfficer, Any): their X-User-ID is not compared to any entity id, so
a shared constant is the canonical form. MerchantAdmin is entity-backed
(identity = the acting Merchant.id), so ownership-gated calls MUST use the
per-instance builder make_merchant_admin_headers(merchant_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "pos_terminal_headers": build_user_headers("pos-terminal-1", "POSTerminal"),
    "fraud_analyst_headers": build_user_headers("analyst-1", "FraudAnalyst"),
    "settlement_officer_headers": build_user_headers("officer-1", "SettlementOfficer"),
    "any_headers": build_user_headers("reader-1", "Any"),
    # Shared MerchantAdmin fallback — ONLY for non-ownership tests (e.g. the
    # wrong-owner denial). Ownership-gated calls must use the builder below.
    "merchant_admin_headers": build_user_headers("merchant-admin-unowned", "MerchantAdmin"),
}


def make_merchant_admin_headers(merchant_id: str) -> dict:
    """MerchantAdmin (entity_backed:Merchant). Pass the owning Merchant.id so
    ownership checks (PRD §2.1) resolve against the acting merchant."""
    return build_user_headers(merchant_id, "MerchantAdmin")


def make_fraud_analyst_headers(user_id: str) -> dict:
    """FraudAnalyst with an explicit opaque analyst id — used to exercise the
    open/confirm segregation-of-duties rule (PRD §2.10)."""
    return build_user_headers(user_id, "FraudAnalyst")


def make_settlement_officer_headers(user_id: str) -> dict:
    """SettlementOfficer with an explicit opaque officer id — used to exercise
    the open/finalize segregation-of-duties rule (PRD §2.10)."""
    return build_user_headers(user_id, "SettlementOfficer")


def make_pos_terminal_headers(user_id: str) -> dict:
    """POSTerminal with an explicit opaque terminal id (identifier is not
    compared to any entity, PRD §2.1)."""
    return build_user_headers(user_id, "POSTerminal")
