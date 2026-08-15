"""Pre-built role headers for every role in the PRD.

All six roles use opaque operator identifiers: X-User-ID is never compared to
any persisted entity's id, so shared constants are safe everywhere. For
requester-owned mutations (submit / cancel of a sample request) build headers
with the requester id via the per-role builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "BiobankAdmin"),
    "coordinator_headers": build_user_headers("coord-1", "ConsentCoordinator"),
    "lab_headers": build_user_headers("lab-1", "LabTechnician"),
    "reviewer_headers": build_user_headers("rev-1", "CommitteeReviewer"),
    "researcher_headers": build_user_headers("researcher-1", "Researcher"),
    "quality_officer_headers": build_user_headers("qo-1", "QualityOfficer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BiobankAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConsentCoordinator")


def make_lab_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitteeReviewer")


def make_researcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Researcher")


def make_quality_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityOfficer")
