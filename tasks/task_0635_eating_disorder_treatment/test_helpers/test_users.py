"""Pre-built role headers for every role in the PRD.

All five roles are opaque operator identities (PRD §2.1): X-User-ID is never
compared to any entity id, and authorization is purely role-based. The shared
constants below are therefore the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "intake_headers": build_user_headers("test-intake-1", "Intake"),
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "dietitian_headers": build_user_headers("test-dietitian-1", "Dietitian"),
    "reviewer_headers": build_user_headers(
        "test-reviewer-1", "UtilizationReviewer"
    ),
}

# Convenience direct handles (used by fixtures and tests).
ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
