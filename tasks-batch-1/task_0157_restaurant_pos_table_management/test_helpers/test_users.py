"""Pre-built role headers for every role in the Restaurant POS PRD.

Four peer roles: Manager, Server, Host, KitchenStaff (PRD §2.1). Of these, only
Server is entity-backed: when X-User-Role is Server, X-User-ID is the id of the
acting StaffMember, and ownership checks compare a resource's staff foreign key
against it. Manager, Host, and KitchenStaff carry an opaque operator id that the
server does not compare against any entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# Server ownership. The Server constant is a fallback only for non-ownership
# paths (e.g. 403/404 checks); ownership-gated Server calls must use
# make_server_headers(staff_member_id).
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "host_headers": build_user_headers("test-host-1", "Host"),
    "kitchen_headers": build_user_headers("test-kitchen-1", "KitchenStaff"),
    "server_headers": build_user_headers("test-server-1", "Server"),
}


def make_server_headers(staff_member_id: str) -> dict:
    """For Server (entity_backed:StaffMember). Pass the acting StaffMember.id as
    X-User-ID whenever the call is ownership-gated (opening/working a check)."""
    return build_user_headers(staff_member_id, "Server")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")


def make_host_headers(user_id: str = "test-host-1") -> dict:
    return build_user_headers(user_id, "Host")


def make_kitchen_headers(user_id: str = "test-kitchen-1") -> dict:
    return build_user_headers(user_id, "KitchenStaff")
