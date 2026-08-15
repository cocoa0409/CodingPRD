"""Pre-built role headers for every role in the PRD (§2.1).

PracticeManager and FieldTechnician are entity-backed roles: their X-User-ID must
equal the acting Practice / Technician id whenever the call is ownership-gated.
Use make_practice_manager_headers(practice_id) / make_field_technician_headers(technician_id)
for those calls; the shared TEST_USERS constants are for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "DistributionAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "ServiceDispatcher"),
    "manufacturer_agent_headers": build_user_headers("test-manufacturer-1", "ManufacturerAgent"),
    # Entity-backed roles: fallback constants ONLY for tests that do not exercise ownership.
    "practice_manager_headers": build_user_headers("test-practice-manager-1", "PracticeManager"),
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
}


def make_practice_manager_headers(practice_id: str) -> dict:
    """PracticeManager is entity-backed by Practice: X-User-ID must be the Practice id
    for any ownership-gated call (PRD §2.1)."""
    return build_user_headers(practice_id, "PracticeManager")


def make_field_technician_headers(technician_id: str) -> dict:
    """FieldTechnician is entity-backed by Technician: X-User-ID must be the Technician id
    for any assignment-gated call (PRD §2.1)."""
    return build_user_headers(technician_id, "FieldTechnician")
