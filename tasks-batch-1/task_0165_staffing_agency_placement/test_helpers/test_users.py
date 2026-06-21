"""Pre-built role headers for every role in the Staffing Agency Placement API.

Recruiter and AccountManager are opaque operator identities — X-User-ID is never
compared to any entity id, so the shared constants are the canonical form.

Client and Candidate are entity-backed: X-User-ID must equal the acting Client's
or Candidate's id for ownership checks to pass. For any ownership-gated call,
use the per-instance builders make_client_headers(client_id) /
make_candidate_headers(candidate_id) with the actual entity id. The shared
constants for these two roles are only valid for tests that do NOT exercise
ownership (e.g. 401/role-rejection cases).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operators — shared constant is canonical.
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    # Entity-backed roles — shared constants are fallbacks for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
}


def make_recruiter_headers(user_id: str = "test-recruiter-1") -> dict:
    """Recruiter is opaque; user_id is an arbitrary operator identifier."""
    return build_user_headers(user_id, "Recruiter")


def make_account_manager_headers(user_id: str = "test-account-manager-1") -> dict:
    """AccountManager is opaque; user_id is an arbitrary operator identifier."""
    return build_user_headers(user_id, "AccountManager")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")


def make_candidate_headers(candidate_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the acting Candidate.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(candidate_id, "Candidate")
