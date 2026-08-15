"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Default operator identities. Segregation-of-duties tests (PRD §2.8) must use
# distinct X-User-ID values for the two inspectors / manager involved.
SAFETY_MANAGER_ID = "sm-1"
SITE_SUPERINTENDENT_ID = "ss-1"
INSPECTOR_ONE_ID = "insp-1"
INSPECTOR_TWO_ID = "insp-2"
COMPLIANCE_AUDITOR_ID = "ca-1"

# Shared constants — safe for calls whose success does not depend on the caller
# owning the subject resource (opaque roles per PRD §2.1).
TEST_USERS = {
    "safety_manager_headers": build_user_headers(SAFETY_MANAGER_ID, "SafetyManager"),
    "site_superintendent_headers": build_user_headers(
        SITE_SUPERINTENDENT_ID, "SiteSuperintendent"
    ),
    "safety_inspector_headers": build_user_headers(INSPECTOR_ONE_ID, "SafetyInspector"),
    "safety_inspector_two_headers": build_user_headers(INSPECTOR_TWO_ID, "SafetyInspector"),
    "compliance_auditor_headers": build_user_headers(
        COMPLIANCE_AUDITOR_ID, "ComplianceAuditor"
    ),
    # Fallback only for non-ownership tests; SubcontractorRep is entity-backed
    # (X-User-ID must equal a real Subcontractor.id for ownership-gated calls).
    "subcontractor_rep_headers": build_user_headers(
        "test-sub-rep-1", "SubcontractorRep"
    ),
}


# Per-instance builders — required for ownership- or identity-sensitive calls.
def make_safety_manager_headers(user_id: str = SAFETY_MANAGER_ID) -> dict:
    return build_user_headers(user_id, "SafetyManager")


def make_site_superintendent_headers(user_id: str = SITE_SUPERINTENDENT_ID) -> dict:
    return build_user_headers(user_id, "SiteSuperintendent")


def make_safety_inspector_headers(user_id: str = INSPECTOR_ONE_ID) -> dict:
    return build_user_headers(user_id, "SafetyInspector")


def make_subcontractor_rep_headers(subcontractor_id: str) -> dict:
    """For SubcontractorRep (entity-backed: Subcontractor). Pass the actual
    Subcontractor.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(subcontractor_id, "SubcontractorRep")


def make_compliance_auditor_headers(user_id: str = COMPLIANCE_AUDITOR_ID) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")
