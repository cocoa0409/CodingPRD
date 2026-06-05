"""Pre-built role headers for every role in the PRD (§2.1).

Three roles exist:
  - UNOSAdmin: opaque identity, not tied to any persisted entity. The shared
    constant is the canonical form.
  - TransplantCenter: entity_backed:TransplantCenter. X-User-ID must equal the
    acting center's id for ownership-gated calls. Use make_center_headers(id).
  - OrganProcurementOrg: entity_backed:OrganProcurementOrg. X-User-ID must equal
    the acting OPO's id for ownership-gated calls. Use make_opo_headers(id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque admin role, and for tests that do not
# exercise ownership (e.g. unauthenticated/authorization/not-found checks).
TEST_USERS = {
    "admin_headers": build_user_headers("test-unos-admin-1", "UNOSAdmin"),
    "center_headers": build_user_headers("test-center-1", "TransplantCenter"),
    "opo_headers": build_user_headers("test-opo-1", "OrganProcurementOrg"),
}


def make_admin_headers() -> dict:
    """UNOSAdmin (opaque). The id is not compared to any entity."""
    return build_user_headers("test-unos-admin-1", "UNOSAdmin")


def make_center_headers(center_id: str) -> dict:
    """TransplantCenter (entity_backed:TransplantCenter). Pass the actual
    TransplantCenter.id as X-User-ID for every ownership-gated call."""
    return build_user_headers(center_id, "TransplantCenter")


def make_opo_headers(opo_id: str) -> dict:
    """OrganProcurementOrg (entity_backed:OrganProcurementOrg). Pass the actual
    OrganProcurementOrg.id as X-User-ID for every ownership-gated call."""
    return build_user_headers(opo_id, "OrganProcurementOrg")
