"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, or admin-acted calls).
# Operator identities are pinned so segregation-of-duties checks are observable.
TEST_USERS = {
    "anonymous_headers": {},
    "admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
    "admin2_headers": build_user_headers("admin-2", "NetworkAdmin"),
    "mod1_headers": build_user_headers("mod-1", "Moderator"),
    "mod2_headers": build_user_headers("mod-2", "Moderator"),
    "mod3_headers": build_user_headers("mod-3", "Moderator"),
    "hub_headers": build_user_headers("hub-1", "HubCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only; ownership-gated calls MUST use the make_* builders below.
    "steward_headers": build_user_headers("test-steward-1", "Steward"),
    "liaison_headers": build_user_headers("test-school-1", "SchoolLiaison"),
}


def make_steward_headers(user_id: str) -> dict:
    """For Steward (entity_backed:Steward). Pass the actual Steward.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Steward")


def make_school_liaison_headers(school_id: str) -> dict:
    """For SchoolLiaison (entity_backed:School). Pass the actual School.id;
    the server rejects any X-User-ID that is not an existing school id."""
    return build_user_headers(school_id, "SchoolLiaison")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_moderator_headers(user_id: str = "mod-1") -> dict:
    return build_user_headers(user_id, "Moderator")


def make_hub_headers(user_id: str = "hub-1") -> dict:
    return build_user_headers(user_id, "HubCoordinator")
