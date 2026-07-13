"""Pre-built role headers for every role in the PRD.

Registrar and SafetyAdministrator carry opaque X-User-IDs not tied to any
entity, so their shared constants are the canonical form. LicensedInspector
and BuildingOwner are entity-backed: ownership checks compare X-User-ID to
Inspector.id / Owner.id respectively, so ownership-gated calls MUST use the
per-instance builders with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "safety_admin_headers": build_user_headers("test-safety-admin-1", "SafetyAdministrator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "licensed_inspector_headers": build_user_headers("test-inspector-1", "LicensedInspector"),
    "building_owner_headers": build_user_headers("test-owner-1", "BuildingOwner"),
}


def make_registrar_headers(user_id: str = "test-registrar-1") -> dict:
    """Registrar (opaque). X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "Registrar")


def make_safety_admin_headers(user_id: str = "test-safety-admin-1") -> dict:
    """SafetyAdministrator (opaque). X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "SafetyAdministrator")


def make_licensed_inspector_headers(user_id: str) -> dict:
    """LicensedInspector (entity_backed:Inspector). Pass the acting Inspector.id
    whenever the call is ownership-gated (start/complete/resolve/close)."""
    return build_user_headers(user_id, "LicensedInspector")


def make_building_owner_headers(user_id: str) -> dict:
    """BuildingOwner (entity_backed:Owner). Pass the device Owner.id whenever
    the call is ownership-gated (fee pay, citation pay/contest, certificate post)."""
    return build_user_headers(user_id, "BuildingOwner")
