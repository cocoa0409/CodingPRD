"""Pre-built role headers for every role in the PRD.

All six roles are opaque operator identities (PRD section 2.1): X-User-ID is
not tied to any persisted entity. Shared constants are therefore the canonical
form. The per-instance builders exist for workflows that distinguish operators
by X-User-ID — segregation of duties on payout approval compares the approver's
X-User-ID against the payout's recorded proposed_by_user_id, so propose and
approve calls must use distinct user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "stars_admin_headers": build_user_headers("test-stars-admin-1", "StarsAdmin"),
    "stars_analyst_headers": build_user_headers("test-stars-analyst-1", "StarsAnalyst"),
    "quality_ops_headers": build_user_headers("test-quality-ops-1", "QualityOps"),
    "survey_coordinator_headers": build_user_headers("test-survey-coord-1", "SurveyCoordinator"),
    "incentive_manager_headers": build_user_headers("test-incentive-mgr-1", "IncentiveManager"),
    "complaints_auditor_headers": build_user_headers("test-complaints-aud-1", "ComplaintsAuditor"),
}


def make_stars_admin_headers(user_id: str = "test-stars-admin-1") -> dict:
    return build_user_headers(user_id, "StarsAdmin")


def make_stars_analyst_headers(user_id: str = "test-stars-analyst-1") -> dict:
    return build_user_headers(user_id, "StarsAnalyst")


def make_quality_ops_headers(user_id: str = "test-quality-ops-1") -> dict:
    return build_user_headers(user_id, "QualityOps")


def make_survey_coordinator_headers(user_id: str = "test-survey-coord-1") -> dict:
    return build_user_headers(user_id, "SurveyCoordinator")


def make_incentive_manager_headers(user_id: str) -> dict:
    """For IncentiveManager. Pass a distinct user_id per operator whenever the
    call participates in segregation of duties (payout propose vs approve)."""
    return build_user_headers(user_id, "IncentiveManager")


def make_complaints_auditor_headers(user_id: str = "test-complaints-aud-1") -> dict:
    return build_user_headers(user_id, "ComplaintsAuditor")
