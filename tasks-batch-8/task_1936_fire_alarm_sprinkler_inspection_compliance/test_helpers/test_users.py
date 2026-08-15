"""Pre-built role headers for every role in the PRD.

FireMarshal is an opaque identity: X-User-ID is not tied to any persisted
entity (the server may record it, e.g. for segregation-of-duties comparison).
ContractorAdmin is entity-backed by Contractor and Technician is entity-backed
by Technician: ownership and assignment checks compare X-User-ID against the
relevant entity id, so ownership-gated calls MUST use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque FireMarshal role, and for tests that
# do not exercise ownership (400-on-bad-payload, 404-on-missing-resource,
# wrong-role checks).
TEST_USERS = {
    "fire_marshal_headers": build_user_headers("test-marshal-1", "FireMarshal"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only; ownership-gated calls must use the make_* builders below.
    "contractor_admin_headers": build_user_headers("test-admin-1", "ContractorAdmin"),
    "technician_headers": build_user_headers("test-tech-1", "Technician"),
}


def make_fire_marshal_headers(user_id: str = "test-marshal-1") -> dict:
    """FireMarshal is opaque; any stable identifier string is acceptable."""
    return build_user_headers(user_id, "FireMarshal")


def make_contractor_admin_headers(contractor_id: str) -> dict:
    """For ContractorAdmin (entity-backed by Contractor). Pass the acting
    Contractor.id whenever the call is ownership-gated."""
    return build_user_headers(contractor_id, "ContractorAdmin")


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity-backed by Technician). Pass the acting
    Technician.id whenever the call is assignment-gated."""
    return build_user_headers(technician_id, "Technician")
