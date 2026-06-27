"""Pre-built role headers for every role in the PRD.

The five operator roles (PlatformAdmin, SystemsDesigner, ProjectManager,
LowVoltageTech, SupportEngineer) are opaque-identity: X-User-ID is an opaque
operator id never compared to any entity, so the shared constant is canonical.

Client is entity-backed: X-User-ID must equal the acting Client entity's id for
ownership checks to pass, so ownership-gated calls MUST use make_client_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "systems_designer_headers": build_user_headers("designer-1", "SystemsDesigner"),
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "low_voltage_tech_headers": build_user_headers("tech-1", "LowVoltageTech"),
    "support_engineer_headers": build_user_headers("support-1", "SupportEngineer"),
    # Shared Client constant: a fallback for non-ownership tests only (e.g.
    # ERR_UNAUTHORIZED role checks). Ownership-gated calls must use the builder.
    "client_headers": build_user_headers("client-fallback-1", "Client"),
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (proposal accept/reject, change-order
    approve/reject)."""
    return build_user_headers(user_id, "Client")
