"""Pre-built role headers for every role in the PRD (§2.1).

`ProjectCoordinator` is the only role whose `X-User-ID` is opaque — the server
never compares it to an entity id, so the shared constant is the canonical form.
The four party-backed roles and the jurisdiction-backed inspector role must
always be built with the real `Party.id` / `Jurisdiction.id` via the
`make_*_headers()` builders whenever the call is ownership-gated.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role — canonical form
    "coordinator_headers": build_user_headers("coordinator-1", "ProjectCoordinator"),
    # party-backed roles — shared constants only for tests that never touch ownership
    # (bad payloads, missing resources, role-permission checks).
    "solar_contractor_headers": build_user_headers("crew-1", "SolarContractor"),
    "roofing_contractor_headers": build_user_headers("roofer-1", "RoofingContractor"),
    "solar_owner_headers": build_user_headers("owner-1", "SolarOwner"),
    "system_owner_headers": build_user_headers("sysowner-1", "SystemOwner"),
    # jurisdiction-backed role
    "ahj_inspector_headers": build_user_headers("ahj-1", "AHJInspector"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    """ProjectCoordinator identity is opaque; any non-empty id is acceptable."""
    return build_user_headers(user_id, "ProjectCoordinator")


def make_solar_contractor_headers(party_id: str) -> dict:
    """Pass the SOLAR_CONTRACTOR Party.id acting as the crew."""
    return build_user_headers(party_id, "SolarContractor")


def make_roofing_contractor_headers(party_id: str) -> dict:
    """Pass the ROOFER Party.id; required by deck-finding and consent actions."""
    return build_user_headers(party_id, "RoofingContractor")


def make_solar_owner_headers(party_id: str) -> dict:
    """Pass the SOLAR_OWNER Party.id; required by its consent decision."""
    return build_user_headers(party_id, "SolarOwner")


def make_system_owner_headers(party_id: str) -> dict:
    """Pass the SYSTEM_OWNER Party.id; required by consent and sourcing review."""
    return build_user_headers(party_id, "SystemOwner")


def make_ahj_inspector_headers(jurisdiction_id: str) -> dict:
    """Pass the Jurisdiction.id; required by permit decisions and inspection results."""
    return build_user_headers(jurisdiction_id, "AHJInspector")
