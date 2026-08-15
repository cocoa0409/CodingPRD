"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. For the entity_backed Hospitalist role, prefer the per-instance
# builder make_hospitalist_headers() whenever the call is ownership-gated.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "hospitalist_headers": build_user_headers("test-hospitalist-1", "Hospitalist"),
    # opaque roles: shared constant is the canonical form.
    "group_admin_headers": build_user_headers("test-admin-1", "GroupAdmin"),
    "specialist_headers": build_user_headers("test-specialist-1", "ConsultingSpecialist"),
}


def make_hospitalist_headers(user_id: str) -> dict:
    """For the Hospitalist role (entity_backed:Hospitalist). Pass the actual
    Hospitalist.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Hospitalist")


def make_group_admin_headers(user_id: str = "test-admin-1") -> dict:
    """GroupAdmin is opaque; user_id is never compared to an entity id."""
    return build_user_headers(user_id, "GroupAdmin")


def make_specialist_headers(user_id: str = "test-specialist-1") -> dict:
    """ConsultingSpecialist is opaque; user_id is never compared to an entity id."""
    return build_user_headers(user_id, "ConsultingSpecialist")
