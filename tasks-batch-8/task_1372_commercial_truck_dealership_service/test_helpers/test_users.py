"""Pre-built role headers for every role in the PRD (§2.1).

FleetCustomer is entity-backed: its X-User-ID must be the id of the acting
CustomerAccount, so ownership-gated calls MUST use make_fleet_customer_headers()
with the real account id. The shared TEST_USERS["fleet_customer_headers"] entry
is a fallback for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "DealershipAdmin"),
    "sales_manager_headers": build_user_headers("sales-mgr-1", "SalesManager"),
    "sales_consultant_headers": build_user_headers("sales-rep-1", "SalesConsultant"),
    "service_manager_headers": build_user_headers("svc-mgr-1", "ServiceManager"),
    "service_advisor_headers": build_user_headers("svc-adv-1", "ServiceAdvisor"),
    "parts_counter_rep_headers": build_user_headers("parts-rep-1", "PartsCounterRep"),
    "warranty_admin_headers": build_user_headers("wadmin-1", "WarrantyAdministrator"),
    "oem_adjudicator_headers": build_user_headers("oem-9", "OEMClaimsAdjudicator"),
    "controller_headers": build_user_headers("controller-1", "Controller"),
    # Fallback for non-ownership calls only; the id matches no real account.
    "fleet_customer_headers": build_user_headers("fleet-customer-unowned", "FleetCustomer"),
}


def make_fleet_customer_headers(customer_account_id: str) -> dict:
    """FleetCustomer is entity-backed: X-User-ID must be the CustomerAccount.id."""
    return build_user_headers(customer_account_id, "FleetCustomer")


def make_warranty_admin_headers(user_id: str) -> dict:
    """WarrantyAdministrator with a specific opaque operator id (SoD anchor)."""
    return build_user_headers(user_id, "WarrantyAdministrator")


def make_oem_adjudicator_headers(user_id: str) -> dict:
    """OEMClaimsAdjudicator with a specific opaque operator id (SoD anchor)."""
    return build_user_headers(user_id, "OEMClaimsAdjudicator")
