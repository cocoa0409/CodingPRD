"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, StoreManager) and for tests
# that do not exercise ownership (400/404/403 checks, catalog reads).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-user-1", "Anonymous"),
    "store_manager_headers": build_user_headers("store-manager-1", "StoreManager"),
    # Fallbacks for entity_backed roles — ONLY for non-ownership tests.
    "member_headers": build_user_headers("member-fallback-1", "Member"),
    "staff_headers": build_user_headers("staff-fallback-1", "Staff"),
}


# ---- Per-instance builders (mandatory for entity_backed roles) ----

def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id whenever the
    call is ownership-gated (subscriptions, appointments, enrollments,
    registrations, orders, shoe pairs owned by that member)."""
    return build_user_headers(user_id, "Member")


def make_staff_headers(user_id: str) -> dict:
    """For Staff (entity_backed:StaffMember). Pass the acting StaffMember.id;
    completing a fitting appointment requires this equal the appointment's
    fitter_id."""
    return build_user_headers(user_id, "Staff")


def make_store_manager_headers(user_id: str = "store-manager-1") -> dict:
    """StoreManager is opaque; id is not tied to any entity."""
    return build_user_headers(user_id, "StoreManager")


def make_anonymous_headers(user_id: str = "anon-user-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
