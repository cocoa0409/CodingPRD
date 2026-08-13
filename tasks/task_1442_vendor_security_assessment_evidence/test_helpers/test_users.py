"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin / RiskAnalyst / SecurityApprover carry opaque operator ids.
VendorContact is entity-backed: its X-User-ID must be the id of a real
VendorContact record whenever the call is ownership-gated, so use
make_vendor_contact_headers(contact["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# vendor-contact ownership (RBAC denials, 400/404 paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "risk_analyst_headers": build_user_headers("test-risk-analyst-1", "RiskAnalyst"),
    "security_approver_headers": build_user_headers("test-security-approver-1", "SecurityApprover"),
    # Fallback for VendorContact only where ownership is irrelevant.
    "vendor_contact_headers": build_user_headers("test-vendor-contact-1", "VendorContact"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_risk_analyst_headers(user_id: str) -> dict:
    """RiskAnalyst (opaque identity). Use distinct user ids for
    segregation-of-duties pairs (plan acceptor vs verifier)."""
    return build_user_headers(user_id, "RiskAnalyst")


def make_security_approver_headers(user_id: str) -> dict:
    """SecurityApprover (opaque identity)."""
    return build_user_headers(user_id, "SecurityApprover")


def make_vendor_contact_headers(contact_id: str) -> dict:
    """VendorContact (entity-backed). Pass the actual VendorContact.id so
    ownership-scoped vendor-side calls resolve to the owning vendor."""
    return build_user_headers(contact_id, "VendorContact")
