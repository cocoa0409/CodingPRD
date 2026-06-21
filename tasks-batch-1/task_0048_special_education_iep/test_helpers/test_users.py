"""Pre-built role headers for every role in the PRD (PRD §2.1).

All four roles — SpecialEdAdmin, CaseManager, Evaluator, Parent — use an
**opaque** identity model (PRD §2.1): X-User-ID is an opaque operator identifier
that is never tied to any persisted entity and is never compared to an entity id.
The shared constants below are therefore the canonical form for every role.

The server does, however, *record* certain X-User-IDs (the requesting CaseManager
on an evaluation, the convening CaseManager on a meeting) purely to enforce
segregation of duties (PRD §2.1). Tests that exercise that boundary must control
which X-User-ID performs the recorded step and which performs the guarded step;
the per-id builders below let a test pin those identifiers explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "admin_headers": build_user_headers("adm_1", "SpecialEdAdmin"),
    "case_manager_headers": build_user_headers("cm_1", "CaseManager"),
    "evaluator_headers": build_user_headers("ev_1", "Evaluator"),
    "parent_headers": build_user_headers("par_1", "Parent"),
}


def make_admin_headers(user_id: str = "adm_1") -> dict:
    return build_user_headers(user_id, "SpecialEdAdmin")


def make_case_manager_headers(user_id: str = "cm_1") -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_evaluator_headers(user_id: str = "ev_1") -> dict:
    return build_user_headers(user_id, "Evaluator")


def make_parent_headers(user_id: str = "par_1") -> dict:
    return build_user_headers(user_id, "Parent")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
