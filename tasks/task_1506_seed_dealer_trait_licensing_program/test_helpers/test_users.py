"""Pre-built role headers for every role in the PRD (§2.1).

DealerAdmin, SalesRep, Agronomist, and ClaimsAdjuster carry opaque operator
identifiers never compared to any entity id. Grower is entity-backed: when the
call is ownership-gated, X-User-ID must be the acting GrowerAccount's id — use
make_grower_headers(grower["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, admin-acted calls).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "DealerAdmin"),
    "salesrep_headers": build_user_headers("test-rep-1", "SalesRep"),
    "agronomist_headers": build_user_headers("test-agronomist-1", "Agronomist"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "DealerAdmin")


def make_salesrep_headers(user_id: str) -> dict:
    """SalesRep with a specific opaque operator id (e.g. a claim filer)."""
    return build_user_headers(user_id, "SalesRep")


def make_agronomist_headers(user_id: str = "test-agronomist-1") -> dict:
    return build_user_headers(user_id, "Agronomist")


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster with a specific opaque operator id. Segregation of duties
    (PRD §3.8) requires the reviewing adjuster's id to differ from the filer's."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_grower_headers(grower_id: str) -> dict:
    """For Grower (entity-backed by GrowerAccount). Pass the actual
    GrowerAccount.id whenever the call is ownership-gated."""
    return build_user_headers(grower_id, "Grower")
