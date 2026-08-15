"""Pre-built role headers for every role in the PRD (section 2.1).

Entity-backed roles (StateInspector, FairManager, RideOperator, TicketClerk,
CrewMember) MUST be built per-instance with the backing entity's id via the
make_*_headers builders whenever the call is ownership- or scope-gated. The
shared constants in TEST_USERS exist only for calls where the caller's
identity does not need to resolve to a real entity row.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: the server does not compare X-User-ID to any entity.
    "admin_headers": build_user_headers("test-admin-1", "StateProgramAdmin"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "inspector_headers": build_user_headers("test-inspector-1", "StateInspector"),
    "manager_headers": build_user_headers("test-manager-1", "FairManager"),
    "operator_headers": build_user_headers("test-operator-1", "RideOperator"),
    "clerk_headers": build_user_headers("test-clerk-1", "TicketClerk"),
    "crew_headers": build_user_headers("test-crew-1", "CrewMember"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """StateProgramAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "StateProgramAdmin")


def make_inspector_headers(inspector_id: str) -> dict:
    """StateInspector is entity_backed by Inspector; pass Inspector.id."""
    return build_user_headers(inspector_id, "StateInspector")


def make_manager_headers(staff_id: str) -> dict:
    """FairManager is entity_backed by a StaffMember carrying SUPERVISOR."""
    return build_user_headers(staff_id, "FairManager")


def make_operator_headers(staff_id: str) -> dict:
    """RideOperator is entity_backed by a StaffMember carrying OPERATOR."""
    return build_user_headers(staff_id, "RideOperator")


def make_clerk_headers(staff_id: str) -> dict:
    """TicketClerk is entity_backed by a StaffMember carrying CLERK."""
    return build_user_headers(staff_id, "TicketClerk")


def make_crew_headers(staff_id: str) -> dict:
    """CrewMember is entity_backed by a StaffMember carrying CREW."""
    return build_user_headers(staff_id, "CrewMember")
