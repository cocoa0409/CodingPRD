"""Pre-built role headers for every role in the PRD.

All three roles (NetworkAdmin, ResortOps, RefundAdmin) are opaque: X-User-ID is
the caller's identity for authentication only and is never compared to any
entity's id. There is no resource-ownership check in this domain, so shared
constants are the canonical form for every role and no per-instance builders are
required.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "network_admin_headers": build_user_headers("network-admin-1", "NetworkAdmin"),
    "resort_ops_headers": build_user_headers("resort-ops-1", "ResortOps"),
    "refund_admin_headers": build_user_headers("refund-admin-1", "RefundAdmin"),
}


def make_network_admin_headers(user_id: str = "network-admin-1") -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_resort_ops_headers(user_id: str = "resort-ops-1") -> dict:
    return build_user_headers(user_id, "ResortOps")


def make_refund_admin_headers(user_id: str = "refund-admin-1") -> dict:
    return build_user_headers(user_id, "RefundAdmin")
