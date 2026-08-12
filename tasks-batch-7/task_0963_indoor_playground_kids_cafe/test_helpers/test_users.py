"""Pre-built role headers for every role in the PRD (§2.1).

Guardian / FrontDesk / CafeStaff / Manager are entity-backed roles: their
X-User-ID must equal a real Guardian or StaffMember id. Use the per-instance
builders below for those; the shared constants cover only the opaque roles
(Anonymous, Admin), whose X-User-ID is never compared to any entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
}


def make_guardian_headers(user_id: str) -> dict:
    """Guardian is entity-backed: pass the actual Guardian.id whenever the
    call is ownership-gated (children, waivers, visits, bookings, orders)."""
    return build_user_headers(user_id, "Guardian")


def make_front_desk_headers(user_id: str) -> dict:
    """FrontDesk is entity-backed: pass the actual StaffMember.id (the member
    must be ACTIVE with role FRONT_DESK)."""
    return build_user_headers(user_id, "FrontDesk")


def make_cafe_staff_headers(user_id: str) -> dict:
    """CafeStaff is entity-backed: pass the actual StaffMember.id (the member
    must be ACTIVE with role CAFE_STAFF)."""
    return build_user_headers(user_id, "CafeStaff")


def make_manager_headers(user_id: str) -> dict:
    """Manager is entity-backed: pass the actual StaffMember.id (the member
    must be ACTIVE with role MANAGER)."""
    return build_user_headers(user_id, "Manager")
