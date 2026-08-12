"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics: Client and Engineer are entity-backed — ownership/assignment
checks compare X-User-ID against the entity's id, so ownership-gated calls MUST
use make_client_headers(entity["id"]) / make_engineer_headers(entity["id"]).
QAChecker and StudioManager are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, listing calls).
TEST_USERS = {
    # opaque roles: canonical form
    "manager_headers": build_user_headers("test-manager-1", "StudioManager"),
    "qa_headers": build_user_headers("test-qa-1", "QAChecker"),
    # entity-backed fallbacks: ONLY for non-ownership-gated calls
    "client_headers": build_user_headers("test-client-1", "Client"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity-backed by the Client record). Pass the actual
    Client.id whenever the call is ownership-gated (own projects, rounds,
    recalls, slot confirmations)."""
    return build_user_headers(user_id, "Client")


def make_engineer_headers(user_id: str) -> dict:
    """For Engineer (entity-backed by the Engineer record). Pass the actual
    Engineer.id whenever the call is assignment-gated (intake, QC, mastering,
    round submission, deliverable builds)."""
    return build_user_headers(user_id, "Engineer")
