"""Pre-built role headers for every role in the PRD (§2.1).

DispatchAdmin is an opaque role: its X-User-ID is never compared to any
entity id, so shared constants are canonical. The other three roles are
entity-backed — X-User-ID must equal the acting entity's id — so each gets a
per-instance builder that fixtures MUST call with the real entity id whenever
the downstream call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constants are the canonical form. Distinct ids are
    # provided so segregation-of-duties scenarios can pick non-colliding
    # adjudicator identities.
    "admin_headers": build_user_headers("admin-1", "DispatchAdmin"),
    "admin2_headers": build_user_headers("admin-2", "DispatchAdmin"),
    "admin3_headers": build_user_headers("admin-3", "DispatchAdmin"),
    # Entity-backed roles: fallback constants for non-ownership calls ONLY
    # (e.g. 400-on-bad-payload probes). Never use these when the call is
    # ownership-gated — use the make_* builders below with the entity's id.
    "donor_coordinator_headers": build_user_headers("test-donor-1", "DonorCoordinator"),
    "volunteer_driver_headers": build_user_headers("test-driver-1", "VolunteerDriver"),
    "agency_coordinator_headers": build_user_headers("test-agency-1", "AgencyCoordinator"),
}


def make_dispatch_admin_headers(user_id: str) -> dict:
    """DispatchAdmin (opaque). Distinct ids matter for segregation of duties."""
    return build_user_headers(user_id, "DispatchAdmin")


def make_donor_coordinator_headers(donor_site_id: str) -> dict:
    """DonorCoordinator (entity-backed by DonorSite). Pass the donor's id."""
    return build_user_headers(donor_site_id, "DonorCoordinator")


def make_volunteer_driver_headers(driver_id: str) -> dict:
    """VolunteerDriver (entity-backed by VolunteerDriver). Pass the driver's id."""
    return build_user_headers(driver_id, "VolunteerDriver")


def make_agency_coordinator_headers(agency_id: str) -> dict:
    """AgencyCoordinator (entity-backed by RecipientAgency). Pass the agency's id."""
    return build_user_headers(agency_id, "AgencyCoordinator")
