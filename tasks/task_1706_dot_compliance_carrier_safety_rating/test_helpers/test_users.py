"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identities: `X-User-ID` is not tied to any
persisted entity, but it IS recorded on created/decided resources and compared
by the segregation-of-duties rules (PRD §2.10). Use the `make_*_headers`
builders whenever a test needs to control the user id (e.g. SoD scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical caller identities for tests that do not
# exercise segregation-of-duties comparisons.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SafetyAdmin"),
    "director_headers": build_user_headers("director-1", "SafetyDirector"),
    "manager_headers": build_user_headers("manager-1", "SafetyManager"),
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "mro_headers": build_user_headers("mro-1", "MedicalReviewOfficer"),
    "insurance_headers": build_user_headers("insurance-1", "InsuranceAnalyst"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyAdmin")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyDirector")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyManager")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_mro_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalReviewOfficer")


def make_insurance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InsuranceAnalyst")
