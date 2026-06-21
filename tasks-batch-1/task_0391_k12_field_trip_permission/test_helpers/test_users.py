"""Pre-built role headers for every role in the PRD.

Per PRD §2.1: there are exactly four roles. `Principal` and `DistrictAdmin` are
opaque operators — their X-User-ID is not tied to any persisted entity, so a
shared constant is the canonical form. `Teacher` and `Guardian` are
entity_backed:Guardian — their X-User-ID must be the id of the acting Guardian
record, and ownership checks compare a resource's foreign-key field to X-User-ID.
For ownership-gated calls, use the per-instance builders with the real Guardian id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, role-permission checks).
TEST_USERS = {
    # Opaque operators — shared constant is the canonical form.
    "principal_headers": build_user_headers("test-principal-1", "Principal"),
    "district_admin_headers": build_user_headers("test-district-admin-1", "DistrictAdmin"),
    # entity_backed:Guardian roles — shared constant is a fallback for
    # non-ownership tests only; ownership-gated calls MUST use the builders below.
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


# Per-instance builders — required for every entity_backed role.
def make_teacher_headers(guardian_id: str) -> dict:
    """For Teacher (entity_backed:Guardian). Pass the acting Guardian.id as
    user_id; that id is what a trip records as organizer_teacher_id and what
    ownership checks compare against."""
    return build_user_headers(guardian_id, "Teacher")


def make_guardian_headers(guardian_id: str) -> dict:
    """For Guardian (entity_backed:Guardian). Pass the acting Guardian.id as
    user_id; ownership checks on a slip/chaperone compare guardian_id to it."""
    return build_user_headers(guardian_id, "Guardian")


def make_principal_headers(user_id: str = "test-principal-1") -> dict:
    """Principal is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "Principal")


def make_district_admin_headers(user_id: str = "test-district-admin-1") -> dict:
    """DistrictAdmin is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "DistrictAdmin")
