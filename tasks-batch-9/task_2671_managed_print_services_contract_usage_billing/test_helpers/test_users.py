"""Pre-built role headers for every role the platform recognises."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# AccountManager, BillingAnalyst and FleetOpsController are identified by an
# opaque user id, so the shared constant is the canonical form for them.
#
# FieldTechnician and CustomerAdmin carry a resource id in X-User-ID (a
# Technician id and a Site id respectively).  Their shared constants are only
# safe for calls that never reach an ownership check — use the per-instance
# builders below whenever the call is ownership-gated.
TEST_USERS = {
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "account_manager_2_headers": build_user_headers("am-2", "AccountManager"),
    "billing_analyst_headers": build_user_headers("ba-1", "BillingAnalyst"),
    "billing_analyst_2_headers": build_user_headers("ba-2", "BillingAnalyst"),
    "fleet_ops_headers": build_user_headers("ops-1", "FleetOpsController"),
    "fleet_ops_2_headers": build_user_headers("ops-2", "FleetOpsController"),
    "field_technician_headers": build_user_headers("tech-1", "FieldTechnician"),
    "customer_admin_headers": build_user_headers("cust-1", "CustomerAdmin"),
}

ACCOUNT_MANAGER_USER_ID = "am-1"
ACCOUNT_MANAGER_2_USER_ID = "am-2"
BILLING_ANALYST_USER_ID = "ba-1"
BILLING_ANALYST_2_USER_ID = "ba-2"
FLEET_OPS_USER_ID = "ops-1"
FLEET_OPS_2_USER_ID = "ops-2"


def make_account_manager_headers(user_id: str) -> dict:
    """AccountManager headers for a specific opaque user id.

    Used by the review-approval flow, where the approver's identity must differ
    from the author's.
    """
    return build_user_headers(user_id, "AccountManager")


def make_billing_analyst_headers(user_id: str) -> dict:
    """BillingAnalyst headers for a specific opaque user id."""
    return build_user_headers(user_id, "BillingAnalyst")


def make_fleet_ops_headers(user_id: str) -> dict:
    """FleetOpsController headers for a specific opaque user id.

    Meter capture stamps this id onto the reading, and exception resolution
    requires a different id from the submitter's.
    """
    return build_user_headers(user_id, "FleetOpsController")


def make_field_technician_headers(technician_id: str) -> dict:
    """FieldTechnician headers. Pass the Technician's own id as X-User-ID."""
    return build_user_headers(technician_id, "FieldTechnician")


def make_customer_admin_headers(site_id: str) -> dict:
    """CustomerAdmin headers. Pass the Site's own id as X-User-ID."""
    return build_user_headers(site_id, "CustomerAdmin")
