"""Pre-built role headers for every role in the PRD (§2.1).

Three roles:
  - `StudioAdmin` — identity: opaque. `X-User-ID` is an opaque operator id that
    the server does not compare to any entity id; the shared constant is the
    canonical form for every StudioAdmin call.
  - `Instructor` — identity: entity_backed:Instructor. `X-User-ID` must equal the
    acting Instructor's `id` on any session-scoped ownership-gated write. Use
    `make_instructor_headers(instructor_id)`.
  - `Member` — identity: entity_backed:Member. `X-User-ID` must equal the acting
    Member's `id` on any booking/waitlist/gift-card ownership-gated write. Use
    `make_member_headers(member_id)`.

Falling back to a shared constant for an entity_backed role on an ownership-gated
call makes every ownership check reject the request — always thread the real
entity id through the per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque StudioAdmin role and for tests that do
# NOT exercise ownership (e.g. 401/403/404 negative tests).
TEST_USERS = {
    "studio_admin_headers": build_user_headers("test-studio-admin-1", "StudioAdmin"),
    # Shared entity_backed constants: ONLY for non-ownership negative tests.
    "instructor_headers": build_user_headers("test-instructor-shared", "Instructor"),
    "member_headers": build_user_headers("test-member-shared", "Member"),
}


def make_studio_admin_headers(opaque_id: str = "test-studio-admin-1") -> dict:
    """For StudioAdmin (identity: opaque)."""
    return build_user_headers(opaque_id, "StudioAdmin")


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    as user_id on any session-scoped ownership-gated call."""
    return build_user_headers(instructor_id, "Instructor")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    on any booking/waitlist/gift-card ownership-gated call."""
    return build_user_headers(member_id, "Member")
