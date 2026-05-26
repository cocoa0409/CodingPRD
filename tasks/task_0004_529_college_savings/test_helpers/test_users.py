"""Pre-built role headers for every role in the PRD.

AccountOwner is `entity_backed:Donor` — use make_account_owner_headers(donor_id)
for ownership-gated calls. CustodianAgent, ComplianceOfficer, and
SystemTaxAuthority are `opaque` — the shared constants are the canonical form.
"""
from typing import Dict
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership semantics (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "account_owner_headers": build_user_headers("test-account-owner-1", "AccountOwner"),
    # opaque roles: shared constants are canonical.
    "custodian_agent_headers": build_user_headers("test-custodian-1", "CustodianAgent"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "compliance_officer_alt_headers": build_user_headers("test-compliance-2", "ComplianceOfficer"),
    "system_tax_authority_headers": build_user_headers("test-tax-authority-1", "SystemTaxAuthority"),
}


def make_account_owner_headers(donor_id: str) -> Dict[str, str]:
    """AccountOwner identity is the Donor.id. Use this whenever the call is
    ownership-gated (any AccountOwner-only operation against a specific account)."""
    return build_user_headers(donor_id, "AccountOwner")


def make_custodian_headers(user_id: str = "test-custodian-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CustodianAgent")


def make_compliance_headers(user_id: str = "test-compliance-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_tax_authority_headers(user_id: str = "test-tax-authority-1") -> Dict[str, str]:
    return build_user_headers(user_id, "SystemTaxAuthority")


def make_anonymous_headers() -> Dict[str, str]:
    """No X-User-Role header — triggers ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
