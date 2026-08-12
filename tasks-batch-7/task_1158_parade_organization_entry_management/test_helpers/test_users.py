"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque identity: X-User-ID is an opaque operator identifier
never compared to a persisted entity UUID, but it IS recorded on resources at
creation (applicant_user_id / judge_user_id / inspector_user_id /
marshal_user_id) and later compared for ownership. Tests therefore build
headers with the exact identifier the scenario needs.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "committee_admin_headers": build_user_headers("committee-admin-1", "CommitteeAdmin"),
    "agency_reviewer_headers": build_user_headers("agency-reviewer-1", "AgencyReviewer"),
    "safety_inspector_headers": build_user_headers("insp_1", "SafetyInspector"),
    "entrant_headers": build_user_headers("entrant_1", "Entrant"),
    "judge_headers": build_user_headers("judge_1", "Judge"),
    "marshal_headers": build_user_headers("marshal_1", "Marshal"),
}


def make_committee_admin_headers(user_id: str = "committee-admin-1") -> dict:
    return build_user_headers(user_id, "CommitteeAdmin")


def make_agency_reviewer_headers(user_id: str = "agency-reviewer-1") -> dict:
    return build_user_headers(user_id, "AgencyReviewer")


def make_safety_inspector_headers(user_id: str) -> dict:
    """SafetyInspector: the id is recorded as inspector_user_id and governs
    the re-inspection segregation-of-duties rule."""
    return build_user_headers(user_id, "SafetyInspector")


def make_entrant_headers(user_id: str) -> dict:
    """Entrant: the id is copied onto the entry as applicant_user_id and
    ownership checks compare X-User-ID against it."""
    return build_user_headers(user_id, "Entrant")


def make_judge_headers(user_id: str) -> dict:
    """Judge: the id is recorded as judge_user_id and governs who may
    submit or reopen the sheet."""
    return build_user_headers(user_id, "Judge")


def make_marshal_headers(user_id: str) -> dict:
    """Marshal: the id named on the assignment (marshal_user_id) governs who
    may confirm or complete it."""
    return build_user_headers(user_id, "Marshal")
