"""Pre-built role headers for every role in the PRD (§2.1).

ClientAdmin and Broker are entity-backed: their X-User-ID must equal the
acting ClientAccount / Broker id whenever a call is ownership-gated. Use
make_client_admin_headers(client_id) / make_broker_headers(broker_id) with the
real entity id for those calls; the shared constants are safe only for tests
that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed:ClientAccount — fallback for non-ownership tests only.
    "client_admin_headers": build_user_headers("test-client-admin-1", "ClientAdmin"),
    "operations_manager_headers": build_user_headers("test-ops-manager-1", "OperationsManager"),
    "dispatch_coordinator_headers": build_user_headers("test-dispatch-1", "DispatchCoordinator"),
    # entity_backed:Broker — fallback for non-ownership tests only.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "qc_reviewer_headers": build_user_headers("test-qc-reviewer-1", "QCReviewer"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
}


def make_client_admin_headers(client_account_id: str) -> dict:
    """ClientAdmin is entity-backed: pass the actual ClientAccount.id whenever
    the call is ownership-gated (submit, cancel, order creation)."""
    return build_user_headers(client_account_id, "ClientAdmin")


def make_broker_headers(broker_id: str) -> dict:
    """Broker is entity-backed: pass the actual Broker.id whenever the call is
    ownership-gated (accept, decline, report, photos, resubmit)."""
    return build_user_headers(broker_id, "Broker")


def make_qc_reviewer_headers(user_id: str) -> dict:
    """QCReviewer is opaque, but a parametrized id is needed to exercise the
    segregation-of-duties rule (reviewer id equal to the assigned broker)."""
    return build_user_headers(user_id, "QCReviewer")
