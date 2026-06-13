"""Pre-built role headers for every role in the PRD.

VenueAdmin and FinanceOfficer are opaque operator identities (X-User-ID is not
matched against any entity id), so a shared constant is the canonical form.
Coordinator and Client are entity-backed: their X-User-ID must equal the acting
Coordinator.id / Client.id for ownership-gated calls, so use the per-instance
builders make_coordinator_headers(id) / make_client_headers(id) once the entity
exists.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "venue_admin_headers": build_user_headers("admin-op-1", "VenueAdmin"),
    "finance_officer_headers": build_user_headers("finance-op-1", "FinanceOfficer"),
    # Entity-backed roles — shared constants are a fallback for NON-ownership
    # tests only (e.g. 401/403-role/404 checks). Ownership-gated calls MUST use
    # the per-instance builders below with the real entity id.
    "coordinator_headers": build_user_headers("coordinator-fallback-1", "Coordinator"),
    "client_headers": build_user_headers("client-fallback-1", "Client"),
}


def make_venue_admin_headers(user_id: str = "admin-op-1") -> dict:
    """VenueAdmin is opaque; any operator id is accepted."""
    return build_user_headers(user_id, "VenueAdmin")


def make_finance_officer_headers(user_id: str = "finance-op-1") -> dict:
    """FinanceOfficer is opaque; any operator id is accepted."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_coordinator_headers(user_id: str) -> dict:
    """For Coordinator (entity_backed:Coordinator). Pass the actual Coordinator.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Coordinator")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Client")
