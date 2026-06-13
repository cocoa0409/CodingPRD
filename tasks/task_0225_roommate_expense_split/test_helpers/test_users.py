"""Pre-built role headers for every role in the PRD.

When X-User-Role is Roommate, X-User-ID is the id of the acting RoommateProfile,
and ownership checks compare the relevant FK on the resource to X-User-ID. So
any ownership-gated Roommate call MUST use make_roommate_headers(profile_id) with
the real profile id. DisputeMediator and PlatformOperator carry opaque operator
identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Roommate calls that do NOT
# exercise ownership (e.g. 401/403/404-on-missing-resource, profile creation).
TEST_USERS = {
    # entity_backed Roommate: shared constant is a fallback for non-ownership tests only.
    "roommate_headers": build_user_headers("test-roommate-1", "Roommate"),
    # opaque roles: shared constant is the canonical form.
    "mediator_headers": build_user_headers("test-mediator-1", "DisputeMediator"),
    "operator_headers": build_user_headers("test-operator-1", "PlatformOperator"),
}


def make_roommate_headers(profile_id: str) -> dict:
    """For the Roommate role (entity_backed:RoommateProfile). Pass the acting
    profile's id as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(profile_id, "Roommate")


def make_mediator_headers(operator_id: str = "test-mediator-1") -> dict:
    """For the DisputeMediator role (opaque operator id). The id is compared only
    against a dispute's filed_by_id for the segregation-of-duties rule."""
    return build_user_headers(operator_id, "DisputeMediator")


def make_operator_headers(operator_id: str = "test-operator-1") -> dict:
    """For the PlatformOperator role (opaque operator id)."""
    return build_user_headers(operator_id, "PlatformOperator")
