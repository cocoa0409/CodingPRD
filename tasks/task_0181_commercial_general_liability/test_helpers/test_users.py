"""Pre-built role headers for every role in the CGL PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# InsurerAdmin, Underwriter, ClaimsAdjuster, PremiumAuditor carry OPAQUE identities:
# X-User-ID is an operator identifier not compared to any stored resource. The shared
# constant is the canonical form for these roles.
# CertificateHolder is ENTITY_BACKED: the shared constant is a fallback usable only for
# tests that do NOT exercise holder ownership (e.g. role-denial 403 tests). For
# ownership-relevant calls, use make_certificate_holder_headers(holder_id).
TEST_USERS = {
    "insurer_admin_headers": build_user_headers("test-admin-1", "InsurerAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "premium_auditor_headers": build_user_headers("test-auditor-1", "PremiumAuditor"),
    "certificate_holder_headers": build_user_headers("test-holder-1", "CertificateHolder"),
}


def make_certificate_holder_headers(user_id: str) -> dict:
    """For CertificateHolder (entity_backed:CertificateHolder). Pass the actual
    CertificateHolder.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CertificateHolder")
