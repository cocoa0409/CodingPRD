"""Pre-built role headers for every role in the PRD (§2.1).

SchemeAdmin and Anonymous are opaque identities (X-User-ID is never compared
to a persisted entity id), so shared constants are canonical for them.
ClientAdmin, Auditor and DecisionMaker are entity-backed: any ownership-gated
or identity-stamped call MUST use the per-instance builder with the actual
entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, unauthenticated).
TEST_USERS = {
    "scheme_admin_headers": build_user_headers("test-scheme-admin-1", "SchemeAdmin"),
    "anonymous_headers": build_user_headers("anonymous-1", "Anonymous"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g. a ClientAdmin rejected on a role-exclusive endpoint).
    "client_admin_headers": build_user_headers("test-client-admin-1", "ClientAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "decision_maker_headers": build_user_headers("test-decision-maker-1",
                                                 "DecisionMaker"),
}


def make_scheme_admin_headers(user_id: str = "test-scheme-admin-1") -> dict:
    return build_user_headers(user_id, "SchemeAdmin")


def make_client_admin_headers(client_id: str) -> dict:
    """For ClientAdmin (entity_backed:Client). Pass the actual Client.id as
    client_id whenever the call is ownership-gated (applications, CAPs, scope
    changes, appeals)."""
    return build_user_headers(client_id, "ClientAdmin")


def make_auditor_headers(auditor_id: str) -> dict:
    """For Auditor (entity_backed:Auditor). Pass the actual Auditor.id as
    auditor_id whenever the call is ownership-gated (start, findings,
    submit-report, CAP review)."""
    return build_user_headers(auditor_id, "Auditor")


def make_decision_maker_headers(decision_maker_id: str) -> dict:
    """For DecisionMaker (entity_backed:DecisionMaker). Pass the actual
    DecisionMaker.id so independence checks and decision stamps use it."""
    return build_user_headers(decision_maker_id, "DecisionMaker")


def make_anonymous_headers(user_id: str = "anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
