"""Pre-built role headers for every role in the PRD.

Subscriber and FleetManager are entity-backed (X-User-ID is the acting Account.id);
ownership-gated calls MUST use the per-instance builders with the real Account id.
FieldTech, OpsAdmin, and Anonymous are opaque (X-User-ID carries no entity meaning).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    # opaque roles: shared constant is the canonical form.
    "field_tech_headers": build_user_headers("test-field-tech-1", "FieldTech"),
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


# Per-instance builders — required for every entity_backed role.
def make_subscriber_headers(user_id: str) -> dict:
    """For Subscriber (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Subscriber")


def make_fleet_manager_headers(user_id: str) -> dict:
    """For FleetManager (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FleetManager")


def make_field_tech_headers(user_id: str = "test-field-tech-1") -> dict:
    """For FieldTech (opaque)."""
    return build_user_headers(user_id, "FieldTech")


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    """For OpsAdmin (opaque)."""
    return build_user_headers(user_id, "OpsAdmin")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    """For Anonymous (opaque)."""
    return build_user_headers(user_id, "Anonymous")


def make_unknown_role_headers(user_id: str = "test-intruder-1") -> dict:
    """Headers carrying an unrecognized X-User-Role, used to exercise ERR_UNAUTHENTICATED."""
    return build_user_headers(user_id, "Intruder")
