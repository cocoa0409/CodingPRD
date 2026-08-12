"""Pre-built role headers for every role in the PRD (§2.1).

Policyholder and ShopOperator are entity-backed: their X-User-ID must be the
id of the acting Policyholder / GlassShop, so ownership-gated calls MUST use
the per-instance builders below. The opaque roles (ClaimAdjuster,
NetworkAuditor, FraudInvestigator, NetworkAdmin) are not tied to any entity
and use the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles; distinct ids keep segregation-of-duties
# checks from firing accidentally between the default adjuster and auditor.
TEST_USERS = {
    # entity_backed fallbacks — ONLY for tests that do not exercise ownership.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
    "shop_operator_headers": build_user_headers("test-shop-1", "ShopOperator"),
    # opaque roles — canonical form.
    "adjuster_headers": build_user_headers("adjuster-1", "ClaimAdjuster"),
    "adjuster2_headers": build_user_headers("adjuster-2", "ClaimAdjuster"),
    "auditor_headers": build_user_headers("auditor-1", "NetworkAuditor"),
    "auditor2_headers": build_user_headers("auditor-2", "NetworkAuditor"),
    "investigator_headers": build_user_headers("investigator-1", "FraudInvestigator"),
    "admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """For Policyholder (entity-backed). Pass the actual Policyholder.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Policyholder")


def make_shop_operator_headers(shop_id: str) -> dict:
    """For ShopOperator (entity-backed). Pass the actual GlassShop.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(shop_id, "ShopOperator")


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimAdjuster with a chosen opaque id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "ClaimAdjuster")


def make_auditor_headers(user_id: str) -> dict:
    """NetworkAuditor with a chosen opaque id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "NetworkAuditor")
