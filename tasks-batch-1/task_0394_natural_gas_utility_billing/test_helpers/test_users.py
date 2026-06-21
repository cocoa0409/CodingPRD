"""Pre-built role headers for every role in the PRD.

Three roles (BillingAdmin, CustomerService, FieldTech) have an opaque identity:
X-User-ID is an opaque operator id never compared to any entity. The Account role is
entity-backed: X-User-ID must equal the acting Account.id, so ownership-gated calls use
make_account_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    "field_tech_headers": build_user_headers("test-field-tech-1", "FieldTech"),
    # Account is entity-backed: this shared constant is a fallback for non-ownership tests
    # (e.g. forbidden-on-another-account where X-User-ID is the WRONG account on purpose).
    "account_headers": build_user_headers("test-account-1", "Account"),
}


def make_billing_admin_headers(user_id: str = "test-billing-admin-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_customer_service_headers(user_id: str = "test-customer-service-1") -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_field_tech_headers(user_id: str = "test-field-tech-1") -> dict:
    return build_user_headers(user_id, "FieldTech")


def make_account_headers(account_id: str) -> dict:
    """For the Account role (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated (the server compares X-User-ID to the resource's
    account_id)."""
    return build_user_headers(account_id, "Account")
