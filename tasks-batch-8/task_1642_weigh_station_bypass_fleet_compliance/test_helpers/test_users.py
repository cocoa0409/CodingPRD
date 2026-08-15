"""Pre-built role headers for every role in the PRD.

CarrierManager is entity-backed by Carrier: X-User-ID is the acting carrier's
id, and ownership checks compare it against the carrier foreign key of the
resource in scope. Ownership-gated calls MUST use make_carrier_manager_headers
with the real carrier id. The other six roles are opaque identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; the carrier_manager entry is a
# fallback for tests that do not exercise ownership (wrong-role checks, bad
# payloads, unresolvable references).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "state_program_manager_headers": build_user_headers("test-spm-1", "StateProgramManager"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "carrier_manager_headers": build_user_headers("test-carrier-manager-1", "CarrierManager"),
    "safety_data_feed_headers": build_user_headers("test-feed-1", "SafetyDataFeed"),
    "telematics_gateway_headers": build_user_headers("test-gateway-1", "TelematicsGateway"),
    "finance_admin_headers": build_user_headers("test-finance-1", "FinanceAdmin"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_state_program_manager_headers(user_id: str = "test-spm-1") -> dict:
    return build_user_headers(user_id, "StateProgramManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer identity is recorded on dispute adjudications and
    override decisions (first_reviewer_id / appeal_reviewer_id / decided_by),
    so tests that exercise segregation of duties pick distinct officer ids."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_carrier_manager_headers(carrier_id: str) -> dict:
    """For CarrierManager (entity_backed:Carrier). Pass the owning Carrier.id
    whenever the call is ownership-gated."""
    return build_user_headers(carrier_id, "CarrierManager")


def make_safety_data_feed_headers(user_id: str = "test-feed-1") -> dict:
    return build_user_headers(user_id, "SafetyDataFeed")


def make_telematics_gateway_headers(user_id: str = "test-gateway-1") -> dict:
    return build_user_headers(user_id, "TelematicsGateway")


def make_finance_admin_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceAdmin")
