"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin / TrustOfficer / TrustManager / Issuer use opaque X-User-ID
values; Issuer ownership is established field-wise (X-User-ID must equal the
indenture's issuer_ref for issuer-scoped operations). Noteholder is
entity-backed: X-User-ID must equal the acting NoteholderAccount.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. Issuer entries here double as the canonical "issuer-1"/"issuer-2"
# operator ids used as issuer_ref values on created indentures.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "trust_officer_headers": build_user_headers("officer-1", "TrustOfficer"),
    "trust_officer_2_headers": build_user_headers("officer-2", "TrustOfficer"),
    "trust_manager_headers": build_user_headers("manager-1", "TrustManager"),
    "trust_manager_2_headers": build_user_headers("manager-2", "TrustManager"),
    "issuer_headers": build_user_headers("issuer-1", "Issuer"),
    "issuer_2_headers": build_user_headers("issuer-2", "Issuer"),
    # Fallback for non-ownership Noteholder calls only (e.g. role-gate tests).
    "noteholder_headers": build_user_headers("test-noteholder-1", "Noteholder"),
}


# Per-instance builders.
def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_trust_officer_headers(user_id: str = "officer-1") -> dict:
    """TrustOfficer (opaque identity). Use a distinct user_id when a test
    exercises segregation of duties."""
    return build_user_headers(user_id, "TrustOfficer")


def make_trust_manager_headers(user_id: str = "manager-1") -> dict:
    """TrustManager (opaque identity). Use a distinct user_id when a test
    exercises segregation of duties."""
    return build_user_headers(user_id, "TrustManager")


def make_issuer_headers(user_id: str) -> dict:
    """Issuer (opaque identity, field-wise ownership). Pass the indenture's
    issuer_ref as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Issuer")


def make_noteholder_headers(user_id: str) -> dict:
    """Noteholder (entity_backed:NoteholderAccount). Pass the actual
    NoteholderAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Noteholder")
