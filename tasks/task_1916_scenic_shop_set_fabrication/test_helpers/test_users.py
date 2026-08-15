"""Pre-built role headers for every role in PRD §2.1.

Roles whose X-User-ID is entity-backed (ClientPM) get a per-instance builder;
all other roles are opaque and can share a single test identity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. ClientPM calls that hit ownership-gated endpoints MUST use
# make_client_pm_headers(client_id) instead.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shop-admin-1", "ShopAdmin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "shop_foreman_headers": build_user_headers("foreman_1", "ShopForeman"),
    "shop_foreman_other_headers": build_user_headers("foreman_9", "ShopForeman"),
    "staff_engineer_headers": build_user_headers("eng_2", "StaffEngineer"),
    "staff_engineer_preparer_headers": build_user_headers("eng_1", "StaffEngineer"),
    "paint_charge_headers": build_user_headers("paint_1", "PaintCharge"),
    "transport_coordinator_headers": build_user_headers("tc_1", "TransportCoordinator"),
    # ClientPM is entity-backed: this fallback exists only for tests that do
    # NOT exercise an ownership-gated call (e.g. purely role-denial probes).
    "client_pm_headers": build_user_headers("test-client-pm-1", "ClientPM"),
    # Bogus role for the auth-negative probe (PRD §2.1).
    "super_user_headers": build_user_headers("test-su-1", "SuperUser"),
}


# Per-instance builder — REQUIRED whenever the call is ownership-gated.
def make_client_pm_headers(client_id: str) -> dict:
    """For ClientPM (entity_backed:Client). Pass the actual Client.id whenever
    the call goes through an ownership check (bid counter/accept/reject,
    finish-sample approve/reject, change-order approve/reject)."""
    return build_user_headers(client_id, "ClientPM")


def make_shop_foreman_headers(user_id: str) -> dict:
    """For ShopForeman (opaque). Useful to differentiate preparers."""
    return build_user_headers(user_id, "ShopForeman")


def make_staff_engineer_headers(user_id: str) -> dict:
    """For StaffEngineer (opaque). Useful to differentiate approver from preparer."""
    return build_user_headers(user_id, "StaffEngineer")


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_paint_charge_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PaintCharge")
