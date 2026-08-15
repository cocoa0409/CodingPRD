"""Pre-built role headers for every role in the PRD (§2.1).

CustomerRep is entity-backed: its X-User-ID must equal the acting Customer.id
whenever the call is ownership-gated (PRD §2.1). The shared
`customer_rep_headers` entry is a fallback for tests that do not exercise
ownership (e.g. role-denial on an endpoint that does not list CustomerRep).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "facility_admin_headers": build_user_headers("test-facadmin-1", "FacilityAdmin"),
    "yard_master_headers": build_user_headers("test-yard-1", "YardMaster"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SafetyOfficer"),
    "transfer_operator_headers": build_user_headers(
        "test-transfer-1", "TransferOperator"
    ),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # Fallback only: safe for role-denial tests, NOT for ownership-gated calls.
    "customer_rep_headers": build_user_headers("test-custrep-1", "CustomerRep"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed (PRD §2.1): pass the owning Customer.id as
    user_id whenever the call is ownership-gated (own railcar/spot-order/invoice
    reads, spot-order create/cancel, invoice pay/dispute)."""
    return build_user_headers(customer_id, "CustomerRep")


def make_facility_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacilityAdmin")


def make_yard_master_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "YardMaster")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_transfer_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransferOperator")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


# Headers carrying no usable identity: X-User-Role does not name a declared
# role, or the headers are absent entirely (PRD §2.1 -> ERR_UNAUTHENTICATED).
UNAUTHENTICATED_HEADERS = {"Content-Type": "application/json"}
