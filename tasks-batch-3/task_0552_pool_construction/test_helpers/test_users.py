"""Pre-built role headers for the five recognized roles (PRD §2.1).

BuilderPM, Designer and Inspector authenticate with opaque operator ids that the server
never compares to an entity id, so their shared constants are the canonical form.

The Owner role's X-User-ID is compared to the target project's owner_user_id, and the
Subcontractor role's X-User-ID must equal the acting CrewAssignment's subcontractor_id.
Both therefore expose a per-instance builder so ownership-gated calls pass the right id.
"""
from prd_bench_local_runner.testing import build_user_headers

# The reusable owner identifier threaded through the default project payload.
DEFAULT_OWNER_USER_ID = "owner-1"

TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "builder_headers": build_user_headers("builder-1", "BuilderPM"),
    "designer_headers": build_user_headers("designer-1", "Designer"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
    # Owner — X-User-ID must equal the project's owner_user_id; the default project
    # is created with owner_user_id="owner-1", so this constant works for that project.
    "owner_headers": build_user_headers(DEFAULT_OWNER_USER_ID, "Owner"),
    # Subcontractor — entity_backed; this placeholder is a fallback for tests that do
    # NOT exercise ownership. Ownership-gated calls MUST use make_subcontractor_headers().
    "subcontractor_headers": build_user_headers("subcontractor-placeholder", "Subcontractor"),
}


def make_owner_headers(owner_user_id: str) -> dict:
    """Headers for the Owner acting on a project whose owner_user_id == owner_user_id."""
    return build_user_headers(owner_user_id, "Owner")


def make_subcontractor_headers(subcontractor_id: str) -> dict:
    """Headers for a Subcontractor. Pass the actual Subcontractor.id whenever the call
    is ownership-gated (completing / cancelling that sub's own crew assignment)."""
    return build_user_headers(subcontractor_id, "Subcontractor")
