"""Pre-built role headers for every role in the PRD.

UnionRepresentative is entity-backed on Union (its X-User-ID must equal the
acting Union's id for ownership-gated calls); every other role is opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership gating. For UnionRepresentative ownership-gated calls, use
# make_union_representative_headers(union["id"]) instead.
TEST_USERS = {
    "lr_admin_headers": build_user_headers("admin-1", "LRAdmin"),
    "lr_manager_headers": build_user_headers("mgr-1", "LRManager"),
    "negotiator_headers": build_user_headers("neg-1", "Negotiator"),
    "negotiator_2_headers": build_user_headers("neg-2", "Negotiator"),
    "negotiator_3_headers": build_user_headers("neg-3", "Negotiator"),
    "chief_negotiator_headers": build_user_headers("chief-1", "ChiefNegotiator"),
    "legal_counsel_headers": build_user_headers("lc-1", "LegalCounsel"),
    # Fallback only for non-ownership paths (e.g. RBAC denial probes).
    "union_representative_headers": build_user_headers("union-rep-opaque", "UnionRepresentative"),
}


def make_union_representative_headers(union_id: str) -> dict:
    """For UnionRepresentative (entity_backed:Union). Pass the actual Union.id
    as union_id whenever the call is ownership-gated (proposal UNION-side
    actions, tally, information-request create, clause/practice DISPUTE)."""
    return build_user_headers(union_id, "UnionRepresentative")


def make_negotiator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Negotiator")


def make_chief_negotiator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChiefNegotiator")


def make_legal_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_lr_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LRManager")


def make_lr_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LRAdmin")
