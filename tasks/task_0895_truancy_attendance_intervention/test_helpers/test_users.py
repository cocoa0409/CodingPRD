"""Pre-built role headers for every role in the PRD.

Administrator and AttendanceClerk carry an opaque X-User-ID that the server
never compares to any entity id, so their shared constants are canonical.
CaseManager and CourtOfficer are entity_backed:Staff — ownership checks compare
a resource's staff foreign key to X-User-ID — so ownership-gated calls use the
per-instance builders make_case_manager_headers(staff_id) /
make_court_officer_headers(staff_id) with the acting Staff member's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "administrator_headers": build_user_headers("admin-1", "Administrator"),
    "attendance_clerk_headers": build_user_headers("clerk-1", "AttendanceClerk"),
    # CaseManager / CourtOfficer shared constants are fallbacks for role-only
    # (non-ownership) tests such as 403-by-role checks.
    "case_manager_headers": build_user_headers("case-manager-1", "CaseManager"),
    "court_officer_headers": build_user_headers("court-officer-1", "CourtOfficer"),
}


def make_case_manager_headers(user_id: str) -> dict:
    """CaseManager (entity_backed:Staff). Pass the acting Staff.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CaseManager")


def make_court_officer_headers(user_id: str) -> dict:
    """CourtOfficer (entity_backed:Staff). Pass the acting Staff.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CourtOfficer")
