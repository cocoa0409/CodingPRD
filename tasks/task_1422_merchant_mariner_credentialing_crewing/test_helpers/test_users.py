"""Pre-built role headers for every role in the PRD (section 2.1).

FleetAdmin, CredentialingOfficer, CrewingManager, and PortCaptain are opaque
roles: their X-User-ID is never compared to an entity id, so the shared
constants below are canonical. Mariner and UnionDispatcher are entity-backed:
any ownership-gated call MUST use make_mariner_headers(mariner["id"]) or
make_union_dispatcher_headers(hall["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "fleet_admin_headers": build_user_headers("fa-100", "FleetAdmin"),
    "fleet_admin_alt_headers": build_user_headers("fa-200", "FleetAdmin"),
    "officer_headers": build_user_headers("co-100", "CredentialingOfficer"),
    "officer_alt_headers": build_user_headers("co-200", "CredentialingOfficer"),
    "crewing_headers": build_user_headers("cm-100", "CrewingManager"),
    "crewing_alt_headers": build_user_headers("cm-200", "CrewingManager"),
    "port_captain_headers": build_user_headers("pc-100", "PortCaptain"),
    # Entity-backed roles — fallback constants for non-ownership calls only.
    "union_dispatcher_headers": build_user_headers("ud-100", "UnionDispatcher"),
    "mariner_headers": build_user_headers("m-100", "Mariner"),
}


def make_fleet_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetAdmin")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CredentialingOfficer")


def make_crewing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CrewingManager")


def make_port_captain_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortCaptain")


def make_union_dispatcher_headers(hall_id: str) -> dict:
    """For UnionDispatcher (entity-backed by UnionHall). Pass the acting
    hall's id whenever the call is hall-scoped."""
    return build_user_headers(hall_id, "UnionDispatcher")


def make_mariner_headers(mariner_id: str) -> dict:
    """For Mariner (entity-backed by Mariner). Pass the acting mariner's id
    whenever the call addresses the mariner's own subtree."""
    return build_user_headers(mariner_id, "Mariner")
