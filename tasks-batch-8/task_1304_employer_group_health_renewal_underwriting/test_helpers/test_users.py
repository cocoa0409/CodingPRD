"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership checks.
TEST_USERS = {
    "underwriter_headers": build_user_headers("uw-001", "Underwriter"),
    "underwriter2_headers": build_user_headers("uw-002", "Underwriter"),
    "senior_underwriter_headers": build_user_headers("su-001", "SeniorUnderwriter"),
    "senior_underwriter2_headers": build_user_headers("su-002", "SeniorUnderwriter"),
    # Broker is entity_backed: shared constant is a fallback for non-ownership tests only.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "compliance_headers": build_user_headers("co-001", "ComplianceOfficer"),
}


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter is opaque; any stable identifier works."""
    return build_user_headers(user_id, "Underwriter")


def make_senior_underwriter_headers(user_id: str) -> dict:
    """SeniorUnderwriter is opaque; any stable identifier works."""
    return build_user_headers(user_id, "SeniorUnderwriter")


def make_broker_headers(broker_id: str) -> dict:
    """For Broker (entity_backed:Broker). Pass the actual Broker.id as the user id
    whenever the call is ownership-gated (counter / accept / broker-side withdraw)."""
    return build_user_headers(broker_id, "Broker")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque and read-only."""
    return build_user_headers(user_id, "ComplianceOfficer")
