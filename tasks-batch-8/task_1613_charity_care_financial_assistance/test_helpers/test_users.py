"""Pre-built role headers for every role in the PRD (§2.1).

FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent,
and ComplianceOfficer carry opaque operator identifiers never compared to any
entity id (though they are compared for segregation of duties, PRD §2.8).
Patient is entity-backed: when the call is ownership-gated, X-User-ID must be
the acting Patient's id — use make_patient_headers(patient["id"]) for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, staff-acted calls).
TEST_USERS = {
    "counselor_headers": build_user_headers("test-counselor-1", "FinancialCounselor"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "AssistanceReviewer"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAdministrator"),
    "collections_headers": build_user_headers("test-collections-1", "CollectionsAgent"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity-backed by Patient). Pass the actual Patient.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Patient")


def make_financial_counselor_headers(user_id: str) -> dict:
    """FinancialCounselor with a specific opaque operator id. Segregation of
    duties (PRD §2.8) compares this id against the finalizing reviewer's id."""
    return build_user_headers(user_id, "FinancialCounselor")


def make_assistance_reviewer_headers(user_id: str) -> dict:
    """AssistanceReviewer with a specific opaque operator id (PRD §2.8)."""
    return build_user_headers(user_id, "AssistanceReviewer")


def make_billing_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAdministrator")


def make_collections_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CollectionsAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
