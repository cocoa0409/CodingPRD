"""Pre-built role headers for the six PRD roles.

Roles other than PlatformAdmin are entity-backed: their X-User-ID must be the
id of the acting staff record whenever a call is ownership-gated. Use the
per-instance builders below with the real entity id in that case; the shared
constants are only safe for calls whose outcome does not depend on the caller
owning the subject resource (bad-payload 400s, missing-resource 404s, or the
opaque PlatformAdmin).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical shared form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Entity-backed roles: fallback for non-ownership checks ONLY.
    "project_manager_headers": build_user_headers("test-project-manager-1", "ProjectManager"),
    "system_designer_headers": build_user_headers("test-system-designer-1", "SystemDesigner"),
    "soil_scientist_headers": build_user_headers("test-soil-scientist-1", "SoilScientist"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "health_officer_headers": build_user_headers("test-health-officer-1", "HealthOfficer"),
}


def make_project_manager_headers(user_id: str) -> dict:
    """ProjectManager is entity-backed: pass the acting ProjectManager record's id."""
    return build_user_headers(user_id, "ProjectManager")


def make_system_designer_headers(user_id: str) -> dict:
    """SystemDesigner is entity-backed: pass the acting SystemDesigner record's id."""
    return build_user_headers(user_id, "SystemDesigner")


def make_soil_scientist_headers(user_id: str) -> dict:
    """SoilScientist is entity-backed: pass the acting SoilScientist record's id."""
    return build_user_headers(user_id, "SoilScientist")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector is entity-backed: pass the acting Inspector record's id."""
    return build_user_headers(user_id, "Inspector")


def make_health_officer_headers(user_id: str) -> dict:
    """HealthOfficer is entity-backed: pass the acting HealthOfficer record's id."""
    return build_user_headers(user_id, "HealthOfficer")
