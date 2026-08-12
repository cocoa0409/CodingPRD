"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. For the entity_backed Landlord role the shared constant is
# a fallback for non-ownership tests only (e.g. a bad-payload 400 or a call
# against a missing resource). For any ownership-gated call, use
# make_landlord_headers(landlord["id"]) with the real Landlord id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "clerk_headers": build_user_headers("clerk-a", "CourtClerk"),
    "process_server_headers": build_user_headers("ps-1", "ProcessServer"),
    "deputy_headers": build_user_headers("dep-1", "SheriffDeputy"),
    "mediator_headers": build_user_headers("med-1", "Mediator"),
}


def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Landlord")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CourtClerk")


def make_process_server_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessServer")


def make_deputy_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SheriffDeputy")


def make_mediator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Mediator")
