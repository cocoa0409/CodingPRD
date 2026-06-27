"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (Customer, Technician) and two are opaque
(ServiceManager, ComplianceOfficer); Anonymous carries an opaque id only used to
satisfy the header requirement on the two open registration endpoints.

For entity-backed roles, ownership-gated calls MUST use the per-instance builder
with the real entity id (make_customer_headers(customer["id"]),
make_technician_headers(tech["id"])). The TEST_USERS shared constants are only
for non-ownership tests (e.g. opaque-role operator calls, 401/403/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "service_manager_headers": build_user_headers("svc-manager-1", "ServiceManager"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    # Anonymous — open registration endpoints only.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


# ─── Per-instance builders (mandatory for entity_backed roles) ───────────────
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id whenever
    the call is ownership-gated on a project/unit the customer owns."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the real Technician.id
    whenever the call is gated on the acting tech being the assigned/install
    technician (visit complete, dispatch start/pause/resolve, install)."""
    return build_user_headers(user_id, "Technician")


def make_service_manager_headers(user_id: str) -> dict:
    """For ServiceManager (opaque). Used where segregation-of-duties compares the
    acting X-User-ID against resolved_by_tech_id (dispatch close)."""
    return build_user_headers(user_id, "ServiceManager")
