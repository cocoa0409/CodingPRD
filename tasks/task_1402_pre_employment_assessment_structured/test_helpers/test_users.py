"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership of an entity-backed resource. The two admin ids exist so that the
# segregation-of-duties rule on guide approval (approver != creator) can be
# exercised with two distinct operators.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "TalentAssessmentAdmin"),
    "admin2_headers": build_user_headers("admin-2", "TalentAssessmentAdmin"),
    "hm_headers": build_user_headers("hm-1", "HiringManager"),
    "hm2_headers": build_user_headers("hm-2", "HiringManager"),
    "do_headers": build_user_headers("do-1", "DecisionOfficer"),
    "co_headers": build_user_headers("co-1", "ComplianceOfficer"),
    # Entity-backed fallbacks — ONLY for tests that never pass an ownership
    # gate against a real entity (e.g. 400-on-bad-payload, 404-on-missing).
    "interviewer_headers": build_user_headers("test-interviewer-1", "Interviewer"),
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "vendorrep_headers": build_user_headers("test-vendor-1", "VendorRepresentative"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "TalentAssessmentAdmin")


def make_hm_headers(user_id: str) -> dict:
    """HiringManager is opaque; pass the id recorded as hiring_manager_id."""
    return build_user_headers(user_id, "HiringManager")


def make_do_headers(user_id: str = "do-1") -> dict:
    return build_user_headers(user_id, "DecisionOfficer")


def make_co_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_interviewer_headers(user_id: str) -> dict:
    """For Interviewer (entity_backed:Interviewer). Pass the actual
    Interviewer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Interviewer")


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Candidate")


def make_vendorrep_headers(user_id: str) -> dict:
    """For VendorRepresentative (entity_backed:AssessmentVendor). Pass the
    actual AssessmentVendor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "VendorRepresentative")
