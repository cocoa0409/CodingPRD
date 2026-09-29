"""Pre-built role headers for every role named in PRD §2.1.

`DistributorLiaison` is the only role whose `X-User-ID` is a real entity id (the
acting Distributor's `id`), so ownership-gated calls MUST use
`make_distributor_liaison_headers(distributor["id"])`. The other five roles carry
opaque operator identifiers that the server never compares to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the five opaque roles, and for liaison tests that
# do not exercise ownership (missing-resource / bad-payload rejections).
TEST_USERS = {
    "network_admin_headers": build_user_headers("u-admin-1", "NetworkAdmin"),
    "affiliate_sales_exec_headers": build_user_headers("u-sales-1", "AffiliateSalesExec"),
    "affiliate_sales_exec_2_headers": build_user_headers("u-sales-2", "AffiliateSalesExec"),
    "revenue_accountant_headers": build_user_headers("u-rev-1", "RevenueAccountant"),
    "revenue_accountant_2_headers": build_user_headers("u-rev-2", "RevenueAccountant"),
    "audit_manager_headers": build_user_headers("u-audit-1", "AuditManager"),
    "audit_manager_2_headers": build_user_headers("u-audit-2", "AuditManager"),
    "rights_administrator_headers": build_user_headers("u-rights-1", "RightsAdministrator"),
    # Fallback only: a liaison identity that matches no persisted Distributor.
    "distributor_liaison_headers": build_user_headers("u-liaison-unbound", "DistributorLiaison"),
}

ROLE_HEADER_KEYS = {
    "NetworkAdmin": "network_admin_headers",
    "AffiliateSalesExec": "affiliate_sales_exec_headers",
    "RevenueAccountant": "revenue_accountant_headers",
    "AuditManager": "audit_manager_headers",
    "RightsAdministrator": "rights_administrator_headers",
    "DistributorLiaison": "distributor_liaison_headers",
}


def make_distributor_liaison_headers(distributor_id: str) -> dict:
    """Headers for the liaison of one operator: X-User-ID is the Distributor id."""
    return build_user_headers(distributor_id, "DistributorLiaison")


def make_network_admin_headers(user_id: str = "u-admin-1") -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_affiliate_sales_exec_headers(user_id: str = "u-sales-1") -> dict:
    return build_user_headers(user_id, "AffiliateSalesExec")


def make_revenue_accountant_headers(user_id: str = "u-rev-1") -> dict:
    return build_user_headers(user_id, "RevenueAccountant")


def make_audit_manager_headers(user_id: str = "u-audit-1") -> dict:
    return build_user_headers(user_id, "AuditManager")


def make_rights_administrator_headers(user_id: str = "u-rights-1") -> dict:
    return build_user_headers(user_id, "RightsAdministrator")


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Build headers for any role by name; `user_id` defaults per role."""
    defaults = {
        "NetworkAdmin": "u-admin-1",
        "AffiliateSalesExec": "u-sales-1",
        "RevenueAccountant": "u-rev-1",
        "AuditManager": "u-audit-1",
        "RightsAdministrator": "u-rights-1",
        "DistributorLiaison": "u-liaison-unbound",
    }
    return build_user_headers(user_id or defaults.get(role, "u-unknown-1"), role)
