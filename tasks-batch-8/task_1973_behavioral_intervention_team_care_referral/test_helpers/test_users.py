"""Pre-built role headers for every role in the PRD (§2.1).

Six roles are entity-backed by StaffMember; ownership-gated calls MUST use the
per-instance builders below with the actual StaffMember id. SystemAdmin is an
opaque identity and its shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for non-ownership tests (bad payloads, 404 probes,
# opaque SystemAdmin operations). Ownership-gated calls must use the builders.
TEST_USERS = {
    "reporter_headers": build_user_headers("test-reporter-1", "Reporter"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "bit_chair_headers": build_user_headers("test-bit-chair-1", "BITChair"),
    "counseling_evaluator_headers": build_user_headers("test-evaluator-1", "CounselingEvaluator"),
    "dean_headers": build_user_headers("test-dean-1", "DeanOfStudents"),
    "privacy_officer_headers": build_user_headers("test-privacy-officer-1", "PrivacyOfficer"),
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
}


# Per-instance builders — required for every entity-backed role whenever the
# call is ownership-gated (PRD §2.1, §2.8).
def make_reporter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Reporter")


def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_bit_chair_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BITChair")


def make_counseling_evaluator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CounselingEvaluator")


def make_dean_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DeanOfStudents")


def make_privacy_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrivacyOfficer")


def make_system_admin_headers(user_id: str = "test-system-admin-1") -> dict:
    """SystemAdmin is opaque (PRD §2.1): any identifier works."""
    return build_user_headers(user_id, "SystemAdmin")
