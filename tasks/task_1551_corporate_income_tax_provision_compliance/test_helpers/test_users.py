"""Pre-built role headers for every role in the PRD.

All five roles are opaque identities (PRD §2.1): `X-User-ID` is not tied to
any persisted entity, so the shared constants are safe for every call. The
single place the identifier's value matters is segregation of duties on
valuation allowance approval — use the per-user builders there.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tax_accountant_headers": build_user_headers("acct-1", "TaxAccountant"),
    "tax_manager_headers": build_user_headers("mgr-1", "TaxManager"),
    "tax_director_headers": build_user_headers("dir-1", "TaxDirector"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_tax_accountant_headers(user_id: str = "acct-1") -> dict:
    """TaxAccountant headers with a specific operator id (audit-trail checks)."""
    return build_user_headers(user_id, "TaxAccountant")


def make_tax_manager_headers(user_id: str = "mgr-1") -> dict:
    """TaxManager headers with a specific operator id (VA preparer identity)."""
    return build_user_headers(user_id, "TaxManager")


def make_tax_director_headers(user_id: str = "dir-1") -> dict:
    """TaxDirector headers with a specific operator id (VA approver identity)."""
    return build_user_headers(user_id, "TaxDirector")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
