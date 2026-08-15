"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: X-User-ID is an operator identifier never compared
to any persisted entity's id (PRD §2.1). Shared constants are therefore the
canonical form for most calls. The per-role builders exist so that
segregation-of-duties workflows (PRD §2.9) can pin a specific X-User-ID for
the requester/opener versus the decider.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "registrar_headers": build_user_headers("reg-1", "Registrar"),
    "counselor_headers": build_user_headers("fc-1", "FinancialCounselor"),
    "reviewer_headers": build_user_headers("ur-2", "UtilizationReviewer"),
    "supervisor_headers": build_user_headers("sup-1", "ClearanceSupervisor"),
    "admin_headers": build_user_headers("sys-1", "SystemAdmin"),
}


def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Registrar")


def make_counselor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinancialCounselor")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilizationReviewer")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClearanceSupervisor")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
