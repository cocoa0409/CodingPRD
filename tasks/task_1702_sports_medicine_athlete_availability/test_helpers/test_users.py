"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use an opaque identity model: X-User-ID is never compared to an
entity id. Shared constants are therefore canonical; the per-user builders exist
for segregation-of-duties scenarios (PRD §3.5) where specific X-User-ID values
(requester, evaluator, decider) must differ or coincide deliberately.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "team_admin": build_user_headers("test-admin-1", "TeamAdmin"),
    "medical_staff": build_user_headers("test-medical-1", "MedicalStaff"),
    "team_physician": build_user_headers("test-physician-1", "TeamPhysician"),
    "performance_staff": build_user_headers("test-performance-1", "PerformanceStaff"),
    "billing_staff": build_user_headers("test-billing-1", "BillingStaff"),
    "coaching_staff": build_user_headers("test-coaching-1", "CoachingStaff"),
}

# A request carrying no user-context headers at all (PRD §2.1).
ANONYMOUS_HEADERS: dict = {}


def medical_headers(user_id: str) -> dict:
    """MedicalStaff headers with a specific X-User-ID (clearance requester /
    status-entry recorder in segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "MedicalStaff")


def physician_headers(user_id: str) -> dict:
    """TeamPhysician headers with a specific X-User-ID (clearance decider in
    segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "TeamPhysician")
