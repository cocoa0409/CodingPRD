"""Pre-built role headers for every role in the PRD.

Four roles (Registrar, Coordinator, Approver, BillingAdmin) carry an opaque
identity — the X-User-ID is an operator identifier never compared to any
entity id. The Client role is entity-backed: its X-User-ID must equal the
acting Client record's id for ownership-gated calls, so a per-instance builder
is provided.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque operator roles.
TEST_USERS = {
    "registrar_headers": build_user_headers("op-registrar-1", "Registrar"),
    "coordinator_headers": build_user_headers("op-coordinator-1", "Coordinator"),
    "approver_headers": build_user_headers("op-approver-1", "Approver"),
    "billing_admin_headers": build_user_headers("op-billing-1", "BillingAdmin"),
    # Fallback for non-ownership Client tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_registrar_headers(user_id: str) -> dict:
    """Registrar headers with an explicit operator id (for SoD / submitter tracking)."""
    return build_user_headers(user_id, "Registrar")


def make_approver_headers(user_id: str) -> dict:
    """Approver headers with an explicit operator id (for SoD tests)."""
    return build_user_headers(user_id, "Approver")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Coordinator")


def make_client_headers(user_id: str) -> dict:
    """Client (entity_backed:Client) headers. Pass the acting Client.id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Client")
