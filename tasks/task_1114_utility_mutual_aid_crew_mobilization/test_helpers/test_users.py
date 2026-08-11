"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (HostCoordinator, RespondingCoordinator, HostSafetyOfficer,
HostFinance, RespondingFinance carry a UtilityCompany id; CrewSupervisor carries
a Crew id) MUST be built per-instance via the make_*_headers builders whenever
the call is ownership-gated. The shared TEST_USERS constants are only for
opaque-role calls and non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: X-User-ID is never compared to a resource id (PRD §2.1).
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # Entity-backed fallbacks — ONLY for tests that do not exercise ownership.
    "host_coordinator_headers": build_user_headers("test-host-1", "HostCoordinator"),
    "responding_coordinator_headers": build_user_headers("test-rsp-1", "RespondingCoordinator"),
    "crew_supervisor_headers": build_user_headers("test-crew-1", "CrewSupervisor"),
    "host_safety_officer_headers": build_user_headers("test-safety-1", "HostSafetyOfficer"),
    "host_finance_headers": build_user_headers("test-finh-1", "HostFinance"),
    "responding_finance_headers": build_user_headers("test-finr-1", "RespondingFinance"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_host_coordinator_headers(user_id: str) -> dict:
    """HostCoordinator (entity_backed: UtilityCompany). Pass the host company's id."""
    return build_user_headers(user_id, "HostCoordinator")


def make_responding_coordinator_headers(user_id: str) -> dict:
    """RespondingCoordinator (entity_backed: UtilityCompany). Pass the responding company's id."""
    return build_user_headers(user_id, "RespondingCoordinator")


def make_crew_supervisor_headers(user_id: str) -> dict:
    """CrewSupervisor (entity_backed: Crew). Pass the crew's id."""
    return build_user_headers(user_id, "CrewSupervisor")


def make_host_safety_officer_headers(user_id: str) -> dict:
    """HostSafetyOfficer (entity_backed: UtilityCompany). Pass the host company's id."""
    return build_user_headers(user_id, "HostSafetyOfficer")


def make_host_finance_headers(user_id: str) -> dict:
    """HostFinance (entity_backed: UtilityCompany). Pass the host company's id."""
    return build_user_headers(user_id, "HostFinance")


def make_responding_finance_headers(user_id: str) -> dict:
    """RespondingFinance (entity_backed: UtilityCompany). Pass the responding company's id."""
    return build_user_headers(user_id, "RespondingFinance")
