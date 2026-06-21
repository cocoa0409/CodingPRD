"""Pre-built role headers for every role in the PRD.

AssetManager and ComplianceOfficer are opaque operator identities — their
X-User-ID is recorded where a workflow demands (submitted_by_user_id /
approved_by_user_id) but is never compared to any entity id. The single
comparison made between two opaque ids is the disposal segregation-of-duties
check, so builders that pin a specific operator id are provided for those tests.

Employee is entity_backed: X-User-ID is the acting Employee entity's id, used by
ownership checks. Use make_employee_headers(employee_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for tests that don't depend on a specific operator id.
TEST_USERS = {
    "asset_manager_headers": build_user_headers("mgr-1", "AssetManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    # A second, distinct compliance officer id — handy where the approver must
    # differ from the submitter.
    "compliance_officer_alt_headers": build_user_headers("co-2", "ComplianceOfficer"),
    # Employee shared constant — fallback for non-ownership reads only.
    "employee_headers": build_user_headers("emp-1", "Employee"),
}


def make_asset_manager_headers(user_id: str) -> dict:
    """AssetManager headers pinned to a specific opaque operator id.

    Use when a disposal segregation-of-duties scenario needs the submitter's
    X-User-ID controlled (e.g. submitted_by_user_id == this id)."""
    return build_user_headers(user_id, "AssetManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers pinned to a specific opaque operator id.

    Use when a disposal segregation-of-duties scenario needs the approver's
    X-User-ID controlled relative to the submitter's."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_employee_headers(employee_id: str) -> dict:
    """Employee (entity_backed) headers. Pass the actual Employee.id as the
    X-User-ID whenever an ownership-gated read is exercised."""
    return build_user_headers(employee_id, "Employee")
