"""Pre-built role headers for every role in the PRD.

Candidate and VendorAgent are entity-backed roles: their X-User-ID must be the
id of the acting Candidate / ScreeningVendor record whenever the call is
ownership-gated. Use the per-instance builders for those calls; the shared
constants exist only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "hr_admin_headers": build_user_headers("test-hr-admin-1", "HRAdmin"),
    "hiring_manager_headers": build_user_headers("test-hiring-manager-1", "HiringManager"),
    "adjudicator_headers": build_user_headers("test-adjudicator-1", "Adjudicator"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Entity-backed roles: fallback only for non-ownership tests.
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "vendor_agent_headers": build_user_headers("test-vendor-agent-1", "VendorAgent"),
}


def make_candidate_headers(candidate_id: str) -> dict:
    """Candidate is entity-backed: pass the actual Candidate.id as user_id
    whenever the call is ownership-gated (consent, dispute, withdrawal)."""
    return build_user_headers(candidate_id, "Candidate")


def make_vendor_agent_headers(vendor_id: str) -> dict:
    """VendorAgent is entity-backed: pass the actual ScreeningVendor.id as
    user_id whenever the call is ownership-gated (report submit, dispute resolve)."""
    return build_user_headers(vendor_id, "VendorAgent")


def make_adjudicator_headers(user_id: str) -> dict:
    """Adjudicator is opaque, but the identity is recorded on assessments,
    orders, and cases (e.g. for segregation of duties) — pick it explicitly."""
    return build_user_headers(user_id, "Adjudicator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque, but the final-notice issuer identity is
    recorded on the case — pick it explicitly for segregation-of-duties tests."""
    return build_user_headers(user_id, "ComplianceOfficer")
