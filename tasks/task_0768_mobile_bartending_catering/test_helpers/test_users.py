"""Pre-built role headers for every role in the PRD (§2.1).

Two identity models:
  * opaque roles (PlatformAdmin, Coordinator, ComplianceOfficer) — X-User-ID is
    an operator identifier not tied to any entity; the shared constant is the
    canonical form.
  * entity_backed roles (Client -> Client.id, Bartender -> Bartender.id) — the
    shared constant is a fallback for NON-ownership tests only; ownership-gated
    calls MUST use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "bartender_headers": build_user_headers("test-bartender-1", "Bartender"),
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id as user_id
    whenever the call is ownership-gated (read/edit/pay/confirm/cancel/menu)."""
    return build_user_headers(user_id, "Client")


def make_bartender_headers(user_id: str) -> dict:
    """For Bartender (entity_backed:Bartender). Pass the acting Bartender.id as
    user_id whenever the call is ownership-gated (check-in / cancel own shift)."""
    return build_user_headers(user_id, "Bartender")
