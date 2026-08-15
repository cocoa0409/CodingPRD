"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (AgencyCoordinator -> PartnerAgency.id, Donor -> Donor.id)
MUST be built per-instance via the make_*_headers() builders whenever the call
is ownership-gated. The shared TEST_USERS constants are safe only for opaque
roles and for tests that never exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "admin_headers": build_user_headers("admin_1", "PlatformAdmin"),
    "admin2_headers": build_user_headers("admin_2", "PlatformAdmin"),
    "caseworker_headers": build_user_headers("cw_1", "CaseWorker"),
    "caseworker2_headers": build_user_headers("cw_2", "CaseWorker"),
    "caseworker3_headers": build_user_headers("cw_3", "CaseWorker"),
    "volunteer_headers": build_user_headers("vol_1", "DistributionVolunteer"),
    "volunteer2_headers": build_user_headers("vol_2", "DistributionVolunteer"),
    # Entity-backed roles — FALLBACK ONLY for non-ownership tests.
    "coordinator_headers": build_user_headers("test-agency-1", "AgencyCoordinator"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_agency_coordinator_headers(agency_id: str) -> dict:
    """AgencyCoordinator is entity-backed by PartnerAgency: X-User-ID must be
    the agency's id for ownership-gated calls (referrals, child/wish creates)."""
    return build_user_headers(agency_id, "AgencyCoordinator")


def make_donor_headers(donor_id: str) -> dict:
    """Donor is entity-backed by Donor: X-User-ID must be the donor's id for
    ownership-gated calls (pledge/confirm/cancel, gift declare/ship, self-read)."""
    return build_user_headers(donor_id, "Donor")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_caseworker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseWorker")


def make_volunteer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistributionVolunteer")
