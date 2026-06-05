"""Pre-built role headers for every role in the PRD.

All four roles (Requester, FoiaOfficer, AppealAuthority, Submitter) are
entity-backed: X-User-ID is interpreted against a persisted entity. Tests whose
success depends on the caller owning / being the subject entity (ownership-gated
payment/withdraw/appeal/object, assignment recording assigned_officer_id, glomar
clearance read from the officer record) MUST use the per-instance builders below
with the actual entity id. The shared TEST_USERS constants are only safe for tests
that do not exercise ownership (e.g. 404 on a missing resource, 422 on a bad
payload, or the missing-auth-headers case).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe only for non-ownership tests (bad-payload 422, missing
# resource 404). NOT for ownership-gated or identity-recording operations.
TEST_USERS = {
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "officer_headers": build_user_headers("test-officer-1", "FoiaOfficer"),
    "appeal_authority_headers": build_user_headers("test-authority-1", "AppealAuthority"),
    "submitter_headers": build_user_headers("test-submitter-1", "Submitter"),
}

# Headers with no auth at all — for the ERR_UNAUTHENTICATED case.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


# Per-instance builders — required for every entity_backed role.
def make_requester_headers(user_id: str) -> dict:
    """For Requester (entity_backed:Requester). Pass the actual Requester.id whenever
    the call is ownership-gated (payment, withdraw, appeal filing)."""
    return build_user_headers(user_id, "Requester")


def make_officer_headers(user_id: str) -> dict:
    """For FoiaOfficer (entity_backed:FoiaOfficer). Pass the actual FoiaOfficer.id
    whenever the call records assigned_officer_id or reads can_invoke_glomar."""
    return build_user_headers(user_id, "FoiaOfficer")


def make_appeal_authority_headers(user_id: str) -> dict:
    """For AppealAuthority (entity_backed:AppealAuthority). Pass the actual
    AppealAuthority.id whenever the call records assigned_authority_id."""
    return build_user_headers(user_id, "AppealAuthority")


def make_submitter_headers(user_id: str) -> dict:
    """For Submitter (entity_backed:Submitter). Pass the actual Submitter.id whenever
    the call is ownership-gated (formally objecting)."""
    return build_user_headers(user_id, "Submitter")
