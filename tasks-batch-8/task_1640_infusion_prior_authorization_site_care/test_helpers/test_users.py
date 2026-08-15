"""Pre-built role headers for every role in the PRD.

All five roles are opaque identities (PRD: X-User-ID is an opaque operator
identifier not tied to any persisted entity). The segregation-of-duties checks
compare recorded user ids against the caller's X-User-ID, so the canonical
fixtures use distinct stable ids per operator (admin-1, coord-1, md-1, md-2,
fin-1, fin-2, sched-1).
"""
from prd_bench_local_runner.testing import build_user_headers

POLICY_ADMIN_HEADERS = build_user_headers("admin-1", "PolicyAdmin")
AUTH_COORDINATOR_HEADERS = build_user_headers("coord-1", "AuthCoordinator")
MEDICAL_DIRECTOR_HEADERS = build_user_headers("md-1", "MedicalDirector")
MEDICAL_DIRECTOR_2_HEADERS = build_user_headers("md-2", "MedicalDirector")
FINANCE_SPECIALIST_HEADERS = build_user_headers("fin-1", "FinanceSpecialist")
FINANCE_SPECIALIST_2_HEADERS = build_user_headers("fin-2", "FinanceSpecialist")
SCHEDULER_HEADERS = build_user_headers("sched-1", "Scheduler")

TEST_USERS = {
    "policy_admin_headers": POLICY_ADMIN_HEADERS,
    "auth_coordinator_headers": AUTH_COORDINATOR_HEADERS,
    "medical_director_headers": MEDICAL_DIRECTOR_HEADERS,
    "medical_director_2_headers": MEDICAL_DIRECTOR_2_HEADERS,
    "finance_specialist_headers": FINANCE_SPECIALIST_HEADERS,
    "finance_specialist_2_headers": FINANCE_SPECIALIST_2_HEADERS,
    "scheduler_headers": SCHEDULER_HEADERS,
}


def make_policy_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PolicyAdmin")


def make_auth_coordinator_headers(user_id: str = "coord-1") -> dict:
    return build_user_headers(user_id, "AuthCoordinator")


def make_medical_director_headers(user_id: str = "md-1") -> dict:
    return build_user_headers(user_id, "MedicalDirector")


def make_finance_specialist_headers(user_id: str = "fin-1") -> dict:
    return build_user_headers(user_id, "FinanceSpecialist")


def make_scheduler_headers(user_id: str = "sched-1") -> dict:
    return build_user_headers(user_id, "Scheduler")
