"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (HOAManager, ComplianceOfficer)
# and for tests that do not exercise entity-backed ownership.
TEST_USERS = {
    # Homeowner and BoardMember are entity_backed:Homeowner — the shared
    # constant is a fallback for non-ownership tests only. For ownership-gated
    # calls, use the per-instance builder with the real Homeowner.id.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "board_member_headers": build_user_headers("test-board-1", "BoardMember"),

    # Opaque roles — no entity binding required.
    "hoa_manager_headers": build_user_headers("test-manager-1", "HOAManager"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),

    # Anonymous role — used to prove ERR_UNAUTHENTICATED gate (PRD §2.1).
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_homeowner_headers(homeowner_id: str) -> dict:
    """Homeowner is entity_backed:Homeowner (PRD §2.1). Pass the real
    Homeowner.id whenever the endpoint is ownership-gated (e.g., POST
    /amenity-reservations, POST /homeowners/{id}/autopay-mandate,
    POST /arc-requests, POST /assessments/{id}/pay)."""
    return build_user_headers(homeowner_id, "Homeowner")


def make_board_member_headers(homeowner_id: str) -> dict:
    """BoardMember is entity_backed:Homeowner (PRD §2.1). Pass the real
    Homeowner.id (whose is_board_member==true) for board-scoped operations
    (POST /arc-requests/{id}/reviews, POST /arc-requests/{id}/finalize,
    POST /motions, POST /motions/{id}/close)."""
    return build_user_headers(homeowner_id, "BoardMember")


# Opaque-role builders — retained for signature symmetry.
def make_hoa_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "HOAManager")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
