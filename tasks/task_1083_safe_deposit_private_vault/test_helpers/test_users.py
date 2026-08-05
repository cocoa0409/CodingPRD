"""Pre-built role headers for every role in the PRD (§2.1).

All five operational roles carry an opaque identity, so shared constants are
the canonical form for them. The Renter role is entity-backed: when a call is
ownership-gated, use make_renter_headers(renter_id) with the actual Renter.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these directly.
TEST_USERS = {
    "vault_admin_headers": build_user_headers("admin-default", "VaultAdmin"),
    "billing_clerk_headers": build_user_headers("clerk-default", "BillingClerk"),
    "vault_officer_headers": build_user_headers("officer-default", "VaultOfficer"),
    "compliance_officer_headers": build_user_headers("compliance-default", "ComplianceOfficer"),
    "renter_headers": build_user_headers("renter-default", "Renter"),
}

# No auth headers — for ERR_UNAUTHENTICATED tests (§2.1).
ANON_HEADERS: dict = {}


def make_vault_admin_headers(user_id: str = "admin-default") -> dict:
    return build_user_headers(user_id, "VaultAdmin")


def make_billing_clerk_headers(user_id: str = "clerk-default") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_vault_officer_headers(user_id: str = "officer-default") -> dict:
    return build_user_headers(user_id, "VaultOfficer")


def make_compliance_officer_headers(user_id: str = "compliance-default") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_renter_headers(user_id: str) -> dict:
    """For the entity-backed Renter role. Pass the actual Renter.id when the
    call is ownership-gated."""
    return build_user_headers(user_id, "Renter")
