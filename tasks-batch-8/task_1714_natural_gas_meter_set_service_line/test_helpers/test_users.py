"""Pre-built role headers for every role in the PRD (§2.1).

Builder and Inspector are entity-backed roles: their X-User-ID must equal the
acting entity's id whenever the call is ownership-gated, so fixtures call the
per-instance builders below with the real entity id. The shared constants are
safe only for opaque roles or for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed — fallback only for calls that are not ownership-gated
    "builder_headers": build_user_headers("test-builder-1", "Builder"),
    # entity_backed — fallback only for calls that are not ownership-gated
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # opaque roles — canonical shared form
    "rep_headers": build_user_headers("rep-1", "NewBusinessRep"),
    "engineer_headers": build_user_headers("eng-1", "DesignEngineer"),
    "clerk_headers": build_user_headers("clerk-b", "BillingClerk"),
    "clerk_c_headers": build_user_headers("clerk-c", "BillingClerk"),
    "coordinator_headers": build_user_headers("perm-1", "PermitCoordinator"),
    "supervisor_headers": build_user_headers("sup-1", "FieldSupervisor"),
    "technician_headers": build_user_headers("tech-1", "MeterTechnician"),
    "gis_analyst_headers": build_user_headers("gis-1", "GISAnalyst"),
    "admin_headers": build_user_headers("admin-1", "SystemAdmin"),
}


def make_builder_headers(user_id: str) -> dict:
    """Builder is entity-backed: pass the owning Builder.id as user_id for any
    ownership-gated call (submit, hold, resume, cancel, load writes, accept-quote,
    commitment accept/propose-revision)."""
    return build_user_headers(user_id, "Builder")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector is entity-backed: pass the acting Inspector.id as user_id for
    record-result and purge/leak witnessing calls."""
    return build_user_headers(user_id, "Inspector")


def make_rep_headers(user_id: str = "rep-1") -> dict:
    return build_user_headers(user_id, "NewBusinessRep")


def make_engineer_headers(user_id: str = "eng-1") -> dict:
    return build_user_headers(user_id, "DesignEngineer")


def make_clerk_headers(user_id: str = "clerk-b") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_coordinator_headers(user_id: str = "perm-1") -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_supervisor_headers(user_id: str = "sup-1") -> dict:
    return build_user_headers(user_id, "FieldSupervisor")


def make_technician_headers(user_id: str = "tech-1") -> dict:
    return build_user_headers(user_id, "MeterTechnician")


def make_gis_analyst_headers(user_id: str = "gis-1") -> dict:
    return build_user_headers(user_id, "GISAnalyst")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
