"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (PRD §2.1): Conductor binds X-User-ID to a
CrewMember id, and CustomerRep binds X-User-ID to a Customer id. Any
ownership-gated call MUST use the per-instance builders below with the real
entity id; the shared constants for those two roles are fallbacks for tests
that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "crew_caller_headers": build_user_headers("test-crew-caller-1", "CrewCaller"),
    "track_inspector_headers": build_user_headers("test-track-inspector-1", "TrackInspector"),
    "settlement_clerk_headers": build_user_headers("test-settlement-clerk-1", "SettlementClerk"),
    "regulator_officer_headers": build_user_headers("test-regulator-officer-1", "RegulatorOfficer"),
    "grant_manager_headers": build_user_headers("test-grant-manager-1", "GrantManager"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "conductor_headers": build_user_headers("test-conductor-1", "Conductor"),
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
}


def make_conductor_headers(crew_member_id: str) -> dict:
    """Conductor is entity-backed by CrewMember (PRD §2.1): pass the real
    CrewMember.id whenever the call is ownership-gated (respond, report-on-duty)."""
    return build_user_headers(crew_member_id, "Conductor")


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed by Customer (PRD §2.1): pass the real
    Customer.id whenever the call is ownership-gated (place/amend/cancel/release,
    demurrage read)."""
    return build_user_headers(customer_id, "CustomerRep")
