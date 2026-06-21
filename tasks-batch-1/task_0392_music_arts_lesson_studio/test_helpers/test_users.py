"""Pre-built role headers for every role in the PRD (PRD 2.1).

Two of the roles are opaque (StudioAdmin, BillingClerk): their X-User-ID is an
operator identifier not tied to any persisted entity, so a shared constant is the
canonical form. Two are entity-backed (Instructor -> Instructor.id, ParentGuardian
-> Family.id): ownership checks compare X-User-ID to the resource's foreign key, so
ownership-gated calls MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "studio_admin_headers": build_user_headers("test-admin-1", "StudioAdmin"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # Entity-backed roles — shared constant is a fallback ONLY for tests that do
    # not exercise ownership (e.g. 401/403/404/422 negative paths).
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "parent_guardian_headers": build_user_headers("test-parent-1", "ParentGuardian"),
}


def make_studio_admin_headers(user_id: str = "test-admin-1") -> dict:
    """StudioAdmin is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "StudioAdmin")


def make_billing_clerk_headers(user_id: str = "test-billing-1") -> dict:
    """BillingClerk is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "BillingClerk")


def make_instructor_headers(user_id: str) -> dict:
    """Instructor is entity_backed:Instructor. Pass the actual Instructor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Instructor")


def make_parent_guardian_headers(user_id: str) -> dict:
    """ParentGuardian is entity_backed:Family. Pass the actual Family.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ParentGuardian")
