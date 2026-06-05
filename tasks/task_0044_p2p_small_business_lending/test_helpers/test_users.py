"""Pre-built role headers for every role in the PRD.

Borrower and Investor are entity-backed: their X-User-ID is the id of the acting
Borrower/Investor and ownership checks compare resource FKs to it (PRD §2.1). Use
the per-instance builders below with the real entity id whenever a call is
ownership-gated. Underwriter, ComplianceOfficer, and PlatformAdmin are opaque
operator identities (PRD §2.1) — the shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
    # opaque operator roles: shared constant is the canonical form.
    "underwriter_headers": build_user_headers("uw_scorer", "Underwriter"),
    "underwriter_approver_headers": build_user_headers("uw_approver", "Underwriter"),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


# --- Per-instance builders — required for every entity_backed role ---

def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the actual Borrower.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Borrower")


def make_investor_headers(user_id: str) -> dict:
    """For Investor (entity_backed:Investor). Pass the actual Investor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Investor")


# --- Builders for opaque operator roles, useful when a distinct operator id matters ---

def make_underwriter_headers(user_id: str) -> dict:
    """For Underwriter (opaque). Distinct user_id is meaningful for the
    segregation-of-duties rule (scorer vs approver, PRD §3.3)."""
    return build_user_headers(user_id, "Underwriter")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> dict:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")
