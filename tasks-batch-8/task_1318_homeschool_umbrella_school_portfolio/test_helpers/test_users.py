"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque staff roles — X-User-ID is an opaque operator
# identifier never compared to an entity id for ownership (PRD §2.1).
TEST_USERS = {
    # Parent is entity_backed:Family — this shared constant is a fallback only
    # for calls whose success does not depend on owning the target resource
    # (e.g., self-registration POST /families). Ownership-gated calls MUST use
    # make_parent_headers(family_id).
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "reviewer_headers": build_user_headers("rev-1", "Reviewer"),
    "reviewer2_headers": build_user_headers("rev-2", "Reviewer"),
    "registrar_headers": build_user_headers("reg-1", "Registrar"),
    "director_headers": build_user_headers("dir-1", "AcademicDirector"),
    "director2_headers": build_user_headers("dir-2", "AcademicDirector"),
    "auditor_headers": build_user_headers("aud-1", "StateAuditor"),
}


def make_parent_headers(user_id: str) -> dict:
    """Parent identity is the owning Family.id (entity_backed). Pass the actual
    family's id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Parent")


def make_reviewer_headers(user_id: str) -> dict:
    """Reviewer with a specific operator id (used to exercise conflict-of-interest
    and segregation-of-duties identity comparisons)."""
    return build_user_headers(user_id, "Reviewer")


def make_director_headers(user_id: str) -> dict:
    """AcademicDirector with a specific operator id (used to exercise the
    evaluator/issuer segregation rule)."""
    return build_user_headers(user_id, "AcademicDirector")
