"""Pre-built role headers for every role in the PRD.

Five operator roles carry an opaque X-User-ID; the Customer role is entity-backed
(X-User-ID must equal the acting Account's id). For operator roles the shared
constant is the canonical form. For the Customer role, ownership-gated calls MUST
use make_customer_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "billing_specialist_headers": build_user_headers("op-billing-1", "BillingSpecialist"),
    "meter_tech_headers": build_user_headers("op-metertech-1", "MeterTech"),
    "collections_officer_headers": build_user_headers("op-collections-1", "CollectionsOfficer"),
    "assistance_caseworker_headers": build_user_headers("op-caseworker-1", "AssistanceCaseworker"),
    "supervisor_headers": build_user_headers("op-supervisor-1", "Supervisor"),
    # Fallback only — for non-ownership tests. Real customer calls use make_customer_headers.
    "customer_headers": build_user_headers("cust-placeholder-1", "Customer"),
}

# Empty headers — used by the missing-auth test only.
NO_AUTH_HEADERS: dict = {}


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_meter_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MeterTech")


def make_collections_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CollectionsOfficer")


def make_assistance_caseworker_headers(user_id: str) -> dict:
    """AssistanceCaseworker with an explicit operator id — used to control the
    requested_by value for segregation-of-duties tests."""
    return build_user_headers(user_id, "AssistanceCaseworker")


def make_supervisor_headers(user_id: str) -> dict:
    """Supervisor with an explicit operator id — used to control the approving
    X-User-ID for segregation-of-duties tests."""
    return build_user_headers(user_id, "Supervisor")


def make_customer_headers(user_id: str) -> dict:
    """For the entity-backed Customer role. Pass the Account.id as user_id whenever
    the call is ownership-gated (a customer may act only on their own account)."""
    return build_user_headers(user_id, "Customer")
