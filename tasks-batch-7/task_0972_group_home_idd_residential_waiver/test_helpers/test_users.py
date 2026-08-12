"""Pre-built role headers for every role in the PRD.

Entity-backed roles (CaseManager, QIDP, DSP) expose per-instance builders;
the shared constants are fallbacks for calls that do not exercise ownership
or identity resolution against a specific staff record.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "agency_admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    "billing_headers": build_user_headers("bill-1", "BillingSpecialist"),
    "billing2_headers": build_user_headers("bill-2", "BillingSpecialist"),
    "compliance_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # Entity-backed shared fallbacks (non-ownership contexts only).
    "case_manager_headers": build_user_headers("test-cm-1", "CaseManager"),
    "qidp_headers": build_user_headers("test-qidp-1", "QIDP"),
    "dsp_headers": build_user_headers("test-dsp-1", "DSP"),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles. Pass the actual
# StaffMember.id as user_id whenever the call is ownership- or identity-gated.
# ---------------------------------------------------------------------------

def make_case_manager_headers(user_id: str) -> dict:
    """CaseManager is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(user_id, "CaseManager")


def make_qidp_headers(user_id: str) -> dict:
    """QIDP is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(user_id, "QIDP")


def make_dsp_headers(user_id: str) -> dict:
    """DSP is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(user_id, "DSP")


def make_billing_headers(user_id: str) -> dict:
    """BillingSpecialist is opaque; user_id is a free operator identifier."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_agency_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_compliance_headers(user_id: str = "test-co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_any_headers(user_id: str = "test-any-1") -> dict:
    return build_user_headers(user_id, "Any")
