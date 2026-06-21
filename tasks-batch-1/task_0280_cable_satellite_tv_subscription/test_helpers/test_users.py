"""Pre-built role headers for every role in the PRD.

BillingAdmin and CustomerServiceAgent carry opaque X-User-ID values not tied to
any entity (PRD §2.1). FieldTechnician is entity-backed by Technician, and
Subscriber is entity-backed by Account — for those, ownership-gated calls MUST
use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "customer_service_agent_headers": build_user_headers("test-csa-1", "CustomerServiceAgent"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests
    # only (e.g. 403-forbidden-role, 404-missing-resource). Ownership-gated calls
    # MUST use the builders below with the actual entity id.
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_field_technician_headers(technician_id: str) -> dict:
    """For FieldTechnician (entity_backed:Technician). Pass the acting Technician.id
    as X-User-ID whenever the call is ownership-gated (dispatch/complete/no-show)."""
    return build_user_headers(technician_id, "FieldTechnician")


def make_subscriber_headers(account_id: str) -> dict:
    """For Subscriber (entity_backed:Account). Pass the owned Account.id as
    X-User-ID whenever the call is ownership-gated (self-service cancel/attach/etc.)."""
    return build_user_headers(account_id, "Subscriber")
