"""Pre-built role headers for every role in the PRD (§2.1).

Four of the five roles carry an opaque identity (AccountManager, GrantWriter,
ComplianceOfficer, Ops); their X-User-ID is never compared to any entity id.
The ClientContact role is entity-backed by Client: its X-User-ID must be the
acting Client's id, and ownership checks compare against it. Tests that exercise
a ClientContact ownership path MUST build headers with make_client_contact_headers(client_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for ClientContact tests that do
# NOT exercise ownership (e.g. a 404-on-missing-resource probe).
TEST_USERS = {
    "account_manager_headers": build_user_headers("test-am-1", "AccountManager"),
    "grant_writer_headers": build_user_headers("test-gw-1", "GrantWriter"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "ops_headers": build_user_headers("test-ops-1", "Ops"),
    # ClientContact shared constant is a non-ownership fallback only; ownership
    # tests must use make_client_contact_headers(client_id).
    "client_contact_headers": build_user_headers("test-cc-1", "ClientContact"),
}


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the acting Client's id as
    X-User-ID whenever the call is ownership-gated (proposal request-changes/approve,
    deliverable approve, revision-request create)."""
    return build_user_headers(client_id, "ClientContact")
