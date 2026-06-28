"""Pre-built role headers for every role in the PRD.

PlanAdmin and Dispatcher carry OPAQUE identity (X-User-ID is not compared to any
entity id), so their shared constants are the canonical form. Technician and
Homeowner are entity_backed; ownership checks compare the resource's crew/owner
FK to X-User-ID, so those roles also expose per-instance builders that take the
backing entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "plan_admin_headers": build_user_headers("test-plan-admin-1", "PlanAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests only
    # (e.g. 400/404/403 negatives). Ownership-gated calls must use the builder below.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
}


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:CrewMember). Pass the CrewMember.id."""
    return build_user_headers(user_id, "Technician")


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the Homeowner.id."""
    return build_user_headers(user_id, "Homeowner")


def make_plan_admin_headers(user_id: str = "test-plan-admin-1") -> dict:
    return build_user_headers(user_id, "PlanAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")
