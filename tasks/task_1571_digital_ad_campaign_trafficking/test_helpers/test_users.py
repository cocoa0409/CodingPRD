"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque: `X-User-ID` is not tied to any persisted entity,
so shared constants are canonical. Per-user builders exist for
segregation-of-duties scenarios, where two distinct operator IDs must be
threaded through propose/decide or reconcile/lock pairs (PRD §3.5, §3.6).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ad_ops_headers": build_user_headers("adops-1", "AdOpsManager"),
    "trafficker_headers": build_user_headers("traff-1", "Trafficker"),
    "analyst_headers": build_user_headers("va-1", "VerificationAnalyst"),
    "billing_headers": build_user_headers("bm-1", "BillingManager"),
    # Second billing operator for segregation-of-duties pairs (lock != reconcile).
    "billing2_headers": build_user_headers("bm-2", "BillingManager"),
}


def make_ad_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdOpsManager")


def make_trafficker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Trafficker")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VerificationAnalyst")


def make_billing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingManager")
