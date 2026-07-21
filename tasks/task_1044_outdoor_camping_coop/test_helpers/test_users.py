"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (StoreStaff, CoopAdmin, Anonymous) and
# for tests that do not exercise Member/Guide ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    "staff_headers": build_user_headers("staff-op-1", "StoreStaff"),
    "admin_headers": build_user_headers("admin-op-1", "CoopAdmin"),
    # entity_backed fallbacks — only for non-ownership tests (e.g. 403/404 checks).
    "member_headers": build_user_headers("member-generic-1", "Member"),
    "guide_headers": build_user_headers("guide-generic-1", "Guide"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (reservations, bookings, trade-in
    counter/accept/reject, special-order confirm, etc.)."""
    return build_user_headers(user_id, "Member")


def make_guide_headers(user_id: str) -> dict:
    """For Guide (entity_backed:Guide). Pass the actual Guide.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Guide")
