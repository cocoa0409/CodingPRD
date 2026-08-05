"""Pre-built role headers for every role in the PRD (§2.1).

StudyManager and CPA are opaque identifiers not tied to any persisted entity;
their shared constants are the canonical form. Engineer and Reviewer are both
backed by the Engineer staff record — for ownership / segregation-of-duties the
X-User-ID MUST be the acting Engineer's real id, supplied via the per-instance
builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical shared constants
    "study_manager_headers": build_user_headers("study-manager-1", "StudyManager"),
    "cpa_headers": build_user_headers("cpa-1", "CPA"),
    # entity_backed fallbacks — non-ownership tests only (401/403/404 shape checks)
    "engineer_headers": build_user_headers("engineer-shared", "Engineer"),
    "reviewer_headers": build_user_headers("reviewer-shared", "Reviewer"),
}


def make_engineer_headers(user_id: str) -> dict:
    """For the Engineer role (entity_backed:Engineer). Pass the actual Engineer.id
    as user_id — this value is compared to study.assigned_engineer_id for ownership."""
    return build_user_headers(user_id, "Engineer")


def make_reviewer_headers(user_id: str) -> dict:
    """For the Reviewer role (entity_backed:Engineer). Pass the acting reviewer's
    Engineer.id — compared to study.assigned_engineer_id for segregation of duties."""
    return build_user_headers(user_id, "Reviewer")


def make_study_manager_headers(user_id: str = "study-manager-1") -> dict:
    return build_user_headers(user_id, "StudyManager")


def make_cpa_headers(user_id: str = "cpa-1") -> dict:
    return build_user_headers(user_id, "CPA")
