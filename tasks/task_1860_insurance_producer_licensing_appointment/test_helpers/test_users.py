"""Pre-built role headers for every role in the PRD (section 2.1).

Producer is entity-backed: when X-User-Role is Producer, X-User-ID must be the
id of the acting Producer record, so ownership-gated calls MUST be built with
make_producer_headers(producer["id"]). The other four roles are opaque operator
identities; shared constants are canonical for them. Two distinct
ComplianceOfficer identities exist so maker-checker segregation-of-duties
scenarios can report with one officer and confirm/dismiss with another.
"""
from prd_bench_local_runner.testing import build_user_headers

LICENSING_COORDINATOR_USER_ID = "licensing-coordinator-1"
OFFICER_A_USER_ID = "officer-a"
OFFICER_B_USER_ID = "officer-b"
FINANCE_OPS_USER_ID = "finance-ops-1"
CARRIER_ADMIN_USER_ID = "carrier-admin-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "licensing_coordinator_headers": build_user_headers(
        LICENSING_COORDINATOR_USER_ID, "LicensingCoordinator"
    ),
    "compliance_officer_a_headers": build_user_headers(OFFICER_A_USER_ID, "ComplianceOfficer"),
    "compliance_officer_b_headers": build_user_headers(OFFICER_B_USER_ID, "ComplianceOfficer"),
    "finance_ops_headers": build_user_headers(FINANCE_OPS_USER_ID, "FinanceOps"),
    "carrier_admin_headers": build_user_headers(CARRIER_ADMIN_USER_ID, "CarrierAdmin"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
}


def make_producer_headers(user_id: str) -> dict:
    """Producer is entity-backed: pass the actual Producer.id whenever the call
    is ownership-gated (submitting own applications, reading own records)."""
    return build_user_headers(user_id, "Producer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque; any distinct user id yields a distinct
    officer for maker-checker purposes."""
    return build_user_headers(user_id, "ComplianceOfficer")
