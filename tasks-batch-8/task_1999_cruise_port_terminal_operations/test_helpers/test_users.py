"""Pre-built role headers for every role in the PRD.

PortAuthorityAdmin, Harbormaster, TerminalOperator, CustomsOfficer, and
BillingClerk are opaque identities: X-User-ID is not tied to any persisted
entity. VesselAgent is entity-backed by Vessel: X-User-ID must equal the id of
the Vessel the agent represents. Ownership-gated calls MUST use
make_vessel_agent_headers(vessel["id"]) with the real vessel id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PortAuthorityAdmin"),
    "harbormaster_headers": build_user_headers("test-hm-1", "Harbormaster"),
    "operator_headers": build_user_headers("test-op-1", "TerminalOperator"),
    "customs_headers": build_user_headers("test-customs-1", "CustomsOfficer"),
    "billing_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. wrong-role probes where no scoped resource exists).
    "vessel_agent_headers": build_user_headers("test-vessel-agent-1", "VesselAgent"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PortAuthorityAdmin")


def make_harbormaster_headers(user_id: str = "test-hm-1") -> dict:
    """Harbormaster (opaque). Pass a distinct user_id when a test needs two
    different harbormaster/operator identities (e.g. segregation of duties)."""
    return build_user_headers(user_id, "Harbormaster")


def make_operator_headers(user_id: str = "test-op-1") -> dict:
    """TerminalOperator (opaque). Pass a distinct user_id when a test needs the
    approver to differ from a service order's requested_by_user_id."""
    return build_user_headers(user_id, "TerminalOperator")


def make_customs_headers(user_id: str = "test-customs-1") -> dict:
    return build_user_headers(user_id, "CustomsOfficer")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_vessel_agent_headers(vessel_id: str) -> dict:
    """For VesselAgent (entity_backed:Vessel). Pass the actual Vessel.id
    whenever the call is ownership-gated (own-vessel port calls and children)."""
    return build_user_headers(vessel_id, "VesselAgent")
