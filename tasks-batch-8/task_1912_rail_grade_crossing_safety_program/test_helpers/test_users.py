"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For LocalAuthority (entity_backed: Locality) the shared constant
# is a fallback for non-ownership paths only; ownership-gated calls MUST use
# make_local_authority_headers(locality["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdministrator"),
    "officer_headers": build_user_headers("officer-1", "RailSafetyOfficer"),
    "officer2_headers": build_user_headers("officer-2", "RailSafetyOfficer"),
    "railroad_headers": build_user_headers("BNSF", "RailroadMaintainer"),
    # Fallback only — never equals a real Locality.id.
    "local_authority_headers": build_user_headers("test-locality-1", "LocalAuthority"),
}


def make_local_authority_headers(locality_id: str) -> dict:
    """For LocalAuthority (entity_backed: Locality). Pass the actual Locality.id
    whenever the call is ownership-gated (quiet zones, closures, road-authority
    work orders)."""
    return build_user_headers(locality_id, "LocalAuthority")


def make_railroad_headers(railroad_code: str) -> dict:
    """For RailroadMaintainer: X-User-ID carries the railroad reporting mark and
    must equal crossing.railroad_code for railroad-side work and flagging."""
    return build_user_headers(railroad_code, "RailroadMaintainer")


def make_officer_headers(user_id: str) -> dict:
    """For RailSafetyOfficer (opaque id, but segregation-of-duties compares
    recorded officer ids on closure agreements)."""
    return build_user_headers(user_id, "RailSafetyOfficer")


def make_admin_headers(user_id: str) -> dict:
    """For ProgramAdministrator (opaque id)."""
    return build_user_headers(user_id, "ProgramAdministrator")
