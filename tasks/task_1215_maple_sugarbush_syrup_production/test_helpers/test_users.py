"""Pre-built role headers for every role in the PRD (§2.1).

FieldCrew and SugarMaker are entity-backed roles: their X-User-ID must equal
the acting CrewMember's id whenever the call carries an operator reference
(collected_by / boiled_by / evaluator_id). Use the per-instance builders for
those calls. SugarhouseManager and CertInspector are opaque roles; the shared
constants are their canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is canonical.
    "manager_headers": build_user_headers("test-manager-1", "SugarhouseManager"),
    "inspector_headers": build_user_headers("test-inspector-1", "CertInspector"),
    # Entity-backed roles: fallback ONLY for tests that do not exercise an
    # ownership-gated operator reference (e.g. RBAC-deny probes).
    "fieldcrew_headers": build_user_headers("test-fieldcrew-1", "FieldCrew"),
    "sugarmaker_headers": build_user_headers("test-sugarmaker-1", "SugarMaker"),
}


def make_fieldcrew_headers(user_id: str) -> dict:
    """FieldCrew is entity-backed by CrewMember. Pass the actual CrewMember.id
    whenever the call is ownership-gated (e.g. collected_by == X-User-ID)."""
    return build_user_headers(user_id, "FieldCrew")


def make_sugarmaker_headers(user_id: str) -> dict:
    """SugarMaker is entity-backed by CrewMember. Pass the actual CrewMember.id
    whenever the call is ownership-gated (boiled_by / evaluator_id)."""
    return build_user_headers(user_id, "SugarMaker")
