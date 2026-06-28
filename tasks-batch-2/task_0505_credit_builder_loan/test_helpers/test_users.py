"""Pre-built role headers for every role in the PRD.

Borrower is entity-backed by the Account: X-User-ID must be the acting Account.id
for ownership-gated calls. LoanServicer / ComplianceOfficer / PlatformAdmin are
opaque operator identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# Borrower ownership (e.g. a 401/403/404 surfaces before any ownership match).
TEST_USERS = {
    # entity_backed role: this shared constant is a fallback for non-ownership tests only.
    "borrower_headers": build_user_headers("test-borrower-unowned", "Borrower"),
    # opaque roles: shared constants are the canonical form.
    "loan_servicer_headers": build_user_headers("servicer-1", "LoanServicer"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


# Per-instance builders.

def make_borrower_headers(account_id: str) -> dict:
    """For Borrower (entity_backed:Account). Pass the owning Account.id as user_id
    whenever the call is ownership-gated (acknowledge, deposits, activate, payments,
    payoff, cancel, charges, autopay)."""
    return build_user_headers(account_id, "Borrower")


def make_loan_servicer_headers(user_id: str = "servicer-1") -> dict:
    """For LoanServicer (opaque). user_id is recorded as funded_by_servicer_user_id
    on funding; pass a specific value where segregation-of-duties matters."""
    return build_user_headers(user_id, "LoanServicer")


def make_compliance_officer_headers(user_id: str = "compliance-1") -> dict:
    """For ComplianceOfficer (opaque). user_id is recorded as signed_by_compliance_user_id
    on disclosure issuance, and is the SoD subject on deposit release."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """For PlatformAdmin (opaque). Authorizes clock and batch-sweep operations."""
    return build_user_headers(user_id, "PlatformAdmin")
