"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Manager (opaque id), Attendant (opaque operator handle),
Member (entity-backed — X-User-ID equals the Member.id).

Manager and Attendant are opaque: their X-User-ID is never compared to a
persisted entity's id, so the shared constants below are the canonical form.
Member is entity_backed: any ownership-gated call (own reload/redeem, own WDF
pay/cancel) MUST use make_member_headers(member["id"]) so X-User-ID equals the
acting member's id. Falling back to the shared constant would make every
ownership check reject the request.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "manager_headers": build_user_headers("manager-op", "Manager"),
    "attendant_headers": build_user_headers("attendant-op", "Attendant"),
    # entity_backed Member — shared constant is a fallback for non-ownership
    # tests only (e.g. 404 on a missing resource, 403 on a foreign resource).
    "member_headers": build_user_headers("member-generic", "Member"),
}


def make_manager_headers(user_id: str = "manager-op") -> dict:
    """Manager is opaque; user_id defaults to the shared operator handle."""
    return build_user_headers(user_id, "Manager")


def make_attendant_headers(attendant_id: str = "attendant-op") -> dict:
    """Attendant is opaque. Pass the attendant operator handle used as
    Shift.attendant_id / intake_attendant_id / logged_by_id when the call is
    shift-ownership-gated."""
    return build_user_headers(attendant_id, "Attendant")


def make_member_headers(member_id: str) -> dict:
    """Member is entity_backed:Member. Pass the actual Member.id as user_id
    whenever the call is ownership-gated (reload/redeem/WDF pay/cancel)."""
    return build_user_headers(member_id, "Member")
