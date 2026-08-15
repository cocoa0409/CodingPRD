"""Pre-built role headers for every role in the PRD.

All nine roles are opaque identities: X-User-ID is not tied to any persisted
entity, and the server never compares it against a resource's `id`. The
recorded identifiers (requester_user_id, teacher_user_id, filer_user_id,
voter_user_id, approver_user_id) are what ownership and segregation-of-duties
checks compare against — so tests that exercise those rules build headers with
a chosen user id via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for every call that does not exercise a user-level
# ownership or segregation rule (creation, transitions, reads, wrong-role
# checks, bad-payload checks).
TEST_USERS = {
    "district_admin_headers": build_user_headers("test-admin-1", "DistrictAdmin"),
    "curriculum_director_headers": build_user_headers("test-director-1", "CurriculumDirector"),
    "instructional_specialist_headers": build_user_headers("test-specialist-1", "InstructionalSpecialist"),
    "board_secretary_headers": build_user_headers("test-secretary-1", "BoardSecretary"),
    "procurement_officer_headers": build_user_headers("test-procurement-1", "ProcurementOfficer"),
    "warehouse_manager_headers": build_user_headers("test-warehouse-1", "WarehouseManager"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "committee_member_headers": build_user_headers("test-committee-1", "CommitteeMember"),
    "community_member_headers": build_user_headers("test-community-1", "CommunityMember"),
}

# Requests with no user-context headers at all (authentication-tier tests).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_district_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistrictAdmin")


def make_curriculum_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CurriculumDirector")


def make_instructional_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InstructionalSpecialist")


def make_board_secretary_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardSecretary")


def make_procurement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementOfficer")


def make_warehouse_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseManager")


def make_teacher_headers(user_id: str) -> dict:
    """For Teacher. The id is recorded as teacher_user_id on reviews and as
    requester_user_id on supplemental requests; ownership and segregation
    checks compare against those recorded values."""
    return build_user_headers(user_id, "Teacher")


def make_committee_member_headers(user_id: str) -> dict:
    """For CommitteeMember. The id is recorded as voter_user_id on votes."""
    return build_user_headers(user_id, "CommitteeMember")


def make_community_member_headers(user_id: str) -> dict:
    """For CommunityMember. The id is recorded as filer_user_id on challenges;
    appeals compare the caller against it."""
    return build_user_headers(user_id, "CommunityMember")
