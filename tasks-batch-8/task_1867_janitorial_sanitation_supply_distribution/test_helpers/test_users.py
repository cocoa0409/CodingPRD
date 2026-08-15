"""Pre-built role headers for every role in the PRD.

DistributorAdmin and SalesRep are opaque identities: X-User-ID is not tied to
any persisted entity. FacilityManager is entity-backed by Facility (X-User-ID
is the acting facility's id) and FieldTechnician is entity-backed by
Technician (X-User-ID is the acting technician's id). Ownership-gated calls
MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "distributor_admin_headers": build_user_headers(
        "test-admin-1", "DistributorAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-1", "SalesRep"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only.
    "facility_manager_headers": build_user_headers(
        "test-facility-manager-1", "FacilityManager"),
    "field_technician_headers": build_user_headers(
        "test-technician-1", "FieldTechnician"),
}


def make_distributor_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "DistributorAdmin")


def make_sales_rep_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_facility_manager_headers(facility_id: str) -> dict:
    """For FacilityManager (entity_backed:Facility). Pass the acting
    Facility.id whenever the call is ownership-gated."""
    return build_user_headers(facility_id, "FacilityManager")


def make_field_technician_headers(technician_id: str) -> dict:
    """For FieldTechnician (entity_backed:Technician). Pass the acting
    Technician.id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "FieldTechnician")
