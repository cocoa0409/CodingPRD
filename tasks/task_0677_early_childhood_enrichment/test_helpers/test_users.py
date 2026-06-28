"""Pre-built role headers for every role in the PRD.

StudioAdmin and FrontDeskStaff identities are opaque operator identifiers
not tied to any persisted entity — their shared constants are the canonical
form. Parent identity is entity_backed:Family — its X-User-ID must equal the
acting Family.id, so ownership-gated calls MUST use make_parent_headers(family_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "studio_admin_headers": build_user_headers("test-admin-1", "StudioAdmin"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDeskStaff"),
    # entity_backed:Family role — shared constant is a fallback for tests that
    # do NOT exercise ownership (e.g. 401/unknown-role paths). Ownership-gated
    # Parent calls MUST use make_parent_headers(family_id) below.
    "parent_headers": build_user_headers("test-parent-family-1", "Parent"),
}


def make_parent_headers(family_id: str) -> dict:
    """For Parent (entity_backed:Family). Pass the acting Family.id as user_id
    whenever the call is ownership-gated (the server compares X-User-ID to the
    resource's owning Family.id)."""
    return build_user_headers(family_id, "Parent")
