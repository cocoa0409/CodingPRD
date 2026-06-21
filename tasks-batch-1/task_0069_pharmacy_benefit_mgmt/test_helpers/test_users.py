"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use an opaque X-User-ID that is never compared to any entity id.
Segregation-of-duties on PA decide compares the deciding director's X-User-ID
against the PA's recorded submitted_by_user_id, so the reviewer who submits and
the director who decides MUST carry DIFFERENT user ids. The shared constants
below use distinct ids per role; make_reviewer_headers / make_director_headers
let a test pin an explicit user id when the submitter/decider identity matters.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque user ids per role.
PLAN_ADMIN_ID = "user-plan-admin-1"
REVIEWER_ID = "user-reviewer-1"
DIRECTOR_ID = "user-director-1"
PROVIDER_ID = "user-provider-1"

TEST_USERS = {
    "plan_admin_headers": build_user_headers(PLAN_ADMIN_ID, "PlanAdmin"),
    "pharmacist_reviewer_headers": build_user_headers(REVIEWER_ID, "PharmacistReviewer"),
    "medical_director_headers": build_user_headers(DIRECTOR_ID, "MedicalDirector"),
    "pharmacy_provider_headers": build_user_headers(PROVIDER_ID, "PharmacyProvider"),
}


def make_reviewer_headers(user_id: str) -> dict:
    """PharmacistReviewer headers bound to an explicit X-User-ID (the submitter)."""
    return build_user_headers(user_id, "PharmacistReviewer")


def make_director_headers(user_id: str) -> dict:
    """MedicalDirector headers bound to an explicit X-User-ID (the decider).
    Pass a value different from the PA submitter to satisfy segregation of duties,
    or equal to it to deliberately trigger ERR_SEGREGATION_OF_DUTIES."""
    return build_user_headers(user_id, "MedicalDirector")
