"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# visitor ownership. For ownership-gated visitor calls use make_visitor_headers.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "privacy_admin_headers": build_user_headers("admin-1", "PrivacyAdmin"),
    "vendor_manager_headers": build_user_headers("vm-1", "VendorManager"),
    "compliance_auditor_headers": build_user_headers("aud-1", "ComplianceAuditor"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "any_headers": build_user_headers("reader-1", "PrivacyAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "visitor_headers": build_user_headers("test-visitor-1", "Visitor"),
}


def make_visitor_headers(user_id: str) -> dict:
    """For the Visitor role (X-User-ID is the acting VisitorProfile id).
    Pass the actual VisitorProfile's id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Visitor")


def make_auditor_headers(user_id: str) -> dict:
    """ComplianceAuditor headers with a specific opaque operator id (SoD tests)."""
    return build_user_headers(user_id, "ComplianceAuditor")
