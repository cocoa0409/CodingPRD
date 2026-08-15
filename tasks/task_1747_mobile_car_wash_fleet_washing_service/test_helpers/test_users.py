"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "auditor_headers": build_user_headers("auditor-1", "QualityAuditor"),
    "auditor_2_headers": build_user_headers("auditor-2", "QualityAuditor"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # entity_backed roles: fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id whenever the call is gated on route-lead / report-filer identity."""
    return build_user_headers(user_id, "Technician")


def make_auditor_headers(user_id: str) -> dict:
    """For QualityAuditor (opaque identity): segregated claim steps need distinct
    auditor user ids (e.g. auditor-1 approves, auditor-2 pays)."""
    return build_user_headers(user_id, "QualityAuditor")
