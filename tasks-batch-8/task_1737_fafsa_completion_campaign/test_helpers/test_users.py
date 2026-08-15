"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (SchoolCoordinator -> School.id, StaffMember/Specialist ->
StaffProfile.id) MUST be built per-instance via the make_* builders whenever the
call is ownership- or scope-gated. The shared constants are safe only for
opaque roles or for tests that do not exercise ownership (400/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "campaign_admin_headers": build_user_headers("test-admin-1", "CampaignAdmin"),
    "match_reviewer_headers": build_user_headers("test-reviewer-1", "MatchReviewer"),
    "data_importer_headers": build_user_headers("test-importer-1", "DataImporter"),
    # Entity-backed fallbacks — non-ownership probes only; never use these for
    # scoped writes (the id matches no real School/StaffProfile).
    "school_coordinator_headers": build_user_headers(
        "test-coordinator-1", "SchoolCoordinator"
    ),
    "staff_member_headers": build_user_headers("test-staff-1", "StaffMember"),
    "specialist_headers": build_user_headers("test-specialist-1", "Specialist"),
}


def make_school_coordinator_headers(school_id: str) -> dict:
    """SchoolCoordinator is entity-backed by School: X-User-ID must be the
    acting school's id for every scoped write (PRD §2.1)."""
    return build_user_headers(school_id, "SchoolCoordinator")


def make_staff_member_headers(staff_profile_id: str) -> dict:
    """StaffMember is entity-backed by StaffProfile: X-User-ID must equal the
    assignment's staff_profile_id on accept/decline (PRD §2.1)."""
    return build_user_headers(staff_profile_id, "StaffMember")


def make_specialist_headers(staff_profile_id: str) -> dict:
    """Specialist is entity-backed by StaffProfile: X-User-ID must equal the
    case's assigned_specialist_id on case actions (PRD §2.1)."""
    return build_user_headers(staff_profile_id, "Specialist")
