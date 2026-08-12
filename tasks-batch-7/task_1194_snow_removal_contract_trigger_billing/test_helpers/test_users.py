"""Pre-built role headers for every role in the PRD.

PlatformAdmin, OpsDispatcher, CrewLead, and ClaimsAdjuster are opaque roles:
the server never compares their X-User-ID to any entity id. Subcontractor
(entity_backed:Subcontractor) and ClientContact (entity_backed:Client) must
carry the acting entity's id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "ops_dispatcher_headers": build_user_headers("test-dispatcher-1", "OpsDispatcher"),
    "crew_lead_headers": build_user_headers("test-crew-1", "CrewLead"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
    "subcontractor_headers": build_user_headers("test-subcontractor-1", "Subcontractor"),
}


# Per-instance builders — required for every entity_backed role.
def make_client_headers(client_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the acting Client.id as
    client_id whenever the call is ownership-gated (challenge, dispute, claim)."""
    return build_user_headers(client_id, "ClientContact")


def make_subcontractor_headers(subcontractor_id: str) -> dict:
    """For Subcontractor (entity_backed:Subcontractor). Pass the acting
    Subcontractor.id whenever the call is ownership-gated (coverage activate /
    fail, assigned-visit start / complete)."""
    return build_user_headers(subcontractor_id, "Subcontractor")


# Opaque-role builders — pass a distinct user_id when the call must differ
# from another actor's id (e.g. dispute segregation of duties).
def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "OpsDispatcher")


def make_crew_headers(user_id: str = "test-crew-1") -> dict:
    return build_user_headers(user_id, "CrewLead")


def make_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")
