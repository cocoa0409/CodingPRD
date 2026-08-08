"""Pre-built role headers for every role in the PRD.

Eight roles carry an opaque identity; FieldTech is entity-backed by a Technician,
so its ownership-gated calls must use make_field_tech_headers(technician_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# resource ownership. The SoD workflows use analyst-1 / officer-1 as the default
# distinct actor identities.
TEST_USERS = {
    "program_admin_headers": build_user_headers("program-admin-1", "ProgramAdmin"),
    "compliance_analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "customer_care_headers": build_user_headers("care-1", "CustomerCare"),
    "eligibility_worker_headers": build_user_headers("eligibility-1", "EligibilityWorker"),
    "dispatcher_headers": build_user_headers("dispatch-1", "Dispatcher"),
    # Fallback constant only — ownership-gated FieldTech calls use the builder below.
    "field_tech_headers": build_user_headers("fieldtech-1", "FieldTech"),
    "noc_operator_headers": build_user_headers("noc-1", "NocOperator"),
    "billing_headers": build_user_headers("billing-1", "Billing"),
}


def make_field_tech_headers(technician_id: str) -> dict:
    """For FieldTech (entity-backed by Technician). Pass the acting Technician.id
    as X-User-ID so install-completion ownership checks pass."""
    return build_user_headers(technician_id, "FieldTech")


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst headers carrying an explicit X-User-ID (submitted_by)."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers carrying an explicit X-User-ID (for SoD checks)."""
    return build_user_headers(user_id, "ComplianceOfficer")
