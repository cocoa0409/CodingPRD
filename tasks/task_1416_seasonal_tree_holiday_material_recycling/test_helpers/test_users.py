"""Pre-built role headers for every role in the PRD (section 2.1).

ProgramAdmin, SiteSupervisor, HaulerPartner, and Anonymous are opaque roles:
X-User-ID is an operator identifier never compared to an entity id, so the
shared constants are their canonical form. Resident and Volunteer are
entity-backed: their X-User-ID must equal the acting Household.id /
Volunteer.id, so ownership-gated calls MUST use the per-instance builders
(make_resident_headers(household["id"]) / make_volunteer_headers(vol["id"])).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "site_supervisor_headers": build_user_headers("sup-1", "SiteSupervisor"),
    "hauler_partner_headers": build_user_headers("hauler-1", "HaulerPartner"),
    # Shared fallbacks for non-ownership tests (404s, malformed payloads).
    "resident_headers": build_user_headers("resident-unbound", "Resident"),
    "volunteer_headers": build_user_headers("volunteer-unbound", "Volunteer"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_site_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteSupervisor")


def make_hauler_partner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HaulerPartner")


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed: pass the acting Household.id as user_id."""
    return build_user_headers(user_id, "Resident")


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer is entity-backed: pass the acting Volunteer.id as user_id."""
    return build_user_headers(user_id, "Volunteer")


def make_anonymous_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Anonymous")
