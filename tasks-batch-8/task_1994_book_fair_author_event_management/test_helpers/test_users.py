"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "organizer_headers": build_user_headers("org_lead_1", "Organizer"),
    # A second opaque organizer id used for segregation-of-duties flows.
    "organizer2_headers": build_user_headers("org_lead_2", "Organizer"),
    # opaque role.
    "cashier_headers": build_user_headers("cashier_1", "Cashier"),
    # opaque role.
    "linestaff_headers": build_user_headers("linestaff_1", "LineStaff"),
    # entity_backed roles: fallback constants for non-ownership tests only.
    "school_coordinator_headers": build_user_headers("test-school-1", "SchoolCoordinator"),
    "publisher_rep_headers": build_user_headers("test-publisher-1", "PublisherRep"),
    "author_rep_headers": build_user_headers("test-author-1", "AuthorRep"),
}


# Per-instance builders — required for every entity_backed role.
def make_school_coordinator_headers(user_id: str) -> dict:
    """For SchoolCoordinator (entity_backed:Party). Pass the actual Party.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SchoolCoordinator")


def make_publisher_rep_headers(user_id: str) -> dict:
    """For PublisherRep (entity_backed:Party). Pass the actual Party.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PublisherRep")


def make_author_rep_headers(user_id: str) -> dict:
    """For AuthorRep (entity_backed:Party). Pass the actual Party.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AuthorRep")


def make_organizer_headers(user_id: str) -> dict:
    """For Organizer (opaque). The id is not tied to any entity but IS recorded
    as created_by_user_id on reconciliations; use a stable explicit id when
    segregation-of-duties matters."""
    return build_user_headers(user_id, "Organizer")


def make_cashier_headers(user_id: str) -> dict:
    """For Cashier (opaque)."""
    return build_user_headers(user_id, "Cashier")


def make_linestaff_headers(user_id: str) -> dict:
    """For LineStaff (opaque)."""
    return build_user_headers(user_id, "LineStaff")
