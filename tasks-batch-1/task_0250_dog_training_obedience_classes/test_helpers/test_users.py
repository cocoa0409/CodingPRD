"""Pre-built role headers for every role in the Dog Training & Obedience Classes PRD (§2.1).

Four roles: Owner and Trainer are entity-backed (X-User-ID is the acting Owner.id /
Trainer.id and is compared on ownership/assignment-gated writes); FrontDesk and
AdminManager are opaque operator identities never matched against a stored record.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for entity-backed-role tests
# whose success does NOT depend on the caller owning the subject resource
# (e.g. RBAC-rejected writes, 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "admin_manager_headers": build_user_headers("test-admin-manager-1", "AdminManager"),
    # Owner / Trainer: shared constants are fallbacks for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "trainer_headers": build_user_headers("test-trainer-1", "Trainer"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id as user_id whenever the
    call is ownership-gated (registering/enrolling a dog, buying a package, withdrawing)."""
    return build_user_headers(user_id, "Owner")


def make_trainer_headers(user_id: str) -> dict:
    """For Trainer (entity_backed:Trainer). Pass the actual Trainer.id as user_id whenever
    the call is assignment-gated (start/complete a session, mark attendance, complete makeup)."""
    return build_user_headers(user_id, "Trainer")
