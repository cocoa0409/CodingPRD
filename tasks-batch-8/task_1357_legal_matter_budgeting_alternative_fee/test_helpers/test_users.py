"""Pre-built role headers for every role in the PRD (section 2.1).

FirmAdmin, PricingAnalyst and ClientContact are opaque roles: X-User-ID is an
operator identifier never compared to any entity id, so the shared constants
are their canonical form.

BillingPartner, ManagingPartner and Timekeeper are entity-backed: X-User-ID is
the id of the acting Timekeeper, and ownership checks compare resource
foreign-key fields (responsible_partner_id, timekeeper_id) to it. For any
ownership-gated call, build headers with the real Timekeeper id via the
make_*_headers builders. The shared constants for these roles are fallbacks
for tests that do not exercise ownership (e.g., 400/404/RBAC denials).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "firm_admin_headers": build_user_headers("admin-1", "FirmAdmin"),
    "pricing_analyst_headers": build_user_headers("pa-1", "PricingAnalyst"),
    "client_contact_headers": build_user_headers("cc-1", "ClientContact"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "billing_partner_headers": build_user_headers("bp-unbound", "BillingPartner"),
    "managing_partner_headers": build_user_headers("mp-unbound", "ManagingPartner"),
    "timekeeper_headers": build_user_headers("tk-unbound", "Timekeeper"),
}


def make_billing_partner_headers(user_id: str) -> dict:
    """BillingPartner headers bound to a real Timekeeper id."""
    return build_user_headers(user_id, "BillingPartner")


def make_managing_partner_headers(user_id: str) -> dict:
    """ManagingPartner headers bound to a real Timekeeper id."""
    return build_user_headers(user_id, "ManagingPartner")


def make_timekeeper_headers(user_id: str) -> dict:
    """Timekeeper headers bound to a real Timekeeper id."""
    return build_user_headers(user_id, "Timekeeper")


def make_pricing_analyst_headers(user_id: str) -> dict:
    """PricingAnalyst headers with a specific operator id (opaque role; used
    by segregation-of-duties tests that must pin requested_by/decided_by)."""
    return build_user_headers(user_id, "PricingAnalyst")
