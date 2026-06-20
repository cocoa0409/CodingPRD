"""Pre-built role headers for every role in the PRD (§2.1).

Four roles are entity-backed (Dispatcher, Coder, Biller, ComplianceOfficer): the
X-User-ID must equal the acting AgencyStaff member's id for ownership/authority
checks. BillingAdmin is opaque: its X-User-ID is not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque BillingAdmin role, and for tests whose
# success does NOT depend on the caller owning a subject resource (400/404/auth).
TEST_USERS = {
    "billing_admin_headers": build_user_headers("admin-operator-1", "BillingAdmin"),
    # Fallback constants for entity-backed roles — use ONLY in non-ownership tests
    # (e.g., 401/403/404). Ownership-gated calls must use the make_*_headers builders.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "coder_headers": build_user_headers("test-coder-1", "Coder"),
    "biller_headers": build_user_headers("test-biller-1", "Biller"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
}


def make_billing_admin_headers() -> dict:
    """BillingAdmin (opaque). The id is not compared to any entity."""
    return build_user_headers("admin-operator-1", "BillingAdmin")


def make_dispatcher_headers(staff_id: str) -> dict:
    """Dispatcher (entity_backed:AgencyStaff). Pass the AgencyStaff.id."""
    return build_user_headers(staff_id, "Dispatcher")


def make_coder_headers(staff_id: str) -> dict:
    """Coder (entity_backed:AgencyStaff). Pass the AgencyStaff.id."""
    return build_user_headers(staff_id, "Coder")


def make_biller_headers(staff_id: str) -> dict:
    """Biller (entity_backed:AgencyStaff). Pass the AgencyStaff.id."""
    return build_user_headers(staff_id, "Biller")


def make_compliance_headers(staff_id: str) -> dict:
    """ComplianceOfficer (entity_backed:AgencyStaff). Pass the AgencyStaff.id;
    the PCS-authority check reads the AgencyStaff record identified by this id."""
    return build_user_headers(staff_id, "ComplianceOfficer")
