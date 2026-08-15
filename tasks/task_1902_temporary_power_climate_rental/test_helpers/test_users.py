"""Pre-built role headers for every role in the PRD (§2.1).

Customer is entity-backed: its X-User-ID must be the id of the acting
Customer record, so ownership-gated calls must go through
make_customer_headers(customer_id). FieldTechnician is opaque but
ownership-compared against a visit's assigned_technician_id, so
arrive/complete calls must go through make_field_technician_headers(tech_id).
The remaining roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles: shared constants are the canonical form.
    "sales_engineer_headers": build_user_headers("sales-1", "SalesEngineer"),
    "depot_manager_headers": build_user_headers("depot-1", "DepotManager"),
    "fleet_dispatcher_headers": build_user_headers("dispatch-1", "FleetDispatcher"),
    "claims_assessor_headers": build_user_headers("claims-1", "ClaimsAssessor"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallbacks for non-ownership contexts only (e.g. 404/400 probes).
    "field_technician_headers": build_user_headers("tech-0", "FieldTechnician"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")


def make_field_technician_headers(user_id: str) -> dict:
    """FieldTechnician identity is compared to a visit's
    assigned_technician_id on arrive/complete (PRD §3.7)."""
    return build_user_headers(user_id, "FieldTechnician")


def make_depot_manager_headers(user_id: str) -> dict:
    """DepotManager with a specific operator id (used for waiver
    segregation-of-duties checks, PRD §3.8)."""
    return build_user_headers(user_id, "DepotManager")


def make_claims_assessor_headers(user_id: str) -> dict:
    """ClaimsAssessor with a specific operator id; the id is recorded as
    assessed_by on assessment (PRD §3.8)."""
    return build_user_headers(user_id, "ClaimsAssessor")
