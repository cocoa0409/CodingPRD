"""Pre-built role headers for every role in the PRD.

All three roles carry an opaque identity (PRD §2.1): the X-User-ID is an
operator identifier never compared to any persisted entity's id. The single
exception is the 1035-exchange segregation-of-duties check, where the
submitter's X-User-ID is recorded and the approver's must differ. For those
flows use make_*_headers() with explicit operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, safe as the canonical form everywhere.
TEST_USERS = {
    "contract_admin_headers": build_user_headers("contract-admin-1", "ContractAdmin"),
    "crediting_officer_headers": build_user_headers("crediting-officer-1", "CreditingOfficer"),
    "compliance_officer_headers": build_user_headers("compliance-officer-1", "ComplianceOfficer"),
}


def make_contract_admin_headers(user_id: str) -> dict:
    """ContractAdmin headers with an explicit operator id (for the recorded
    1035-exchange submitter)."""
    return build_user_headers(user_id, "ContractAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with an explicit operator id (for the
    1035-exchange approver in the segregation-of-duties check)."""
    return build_user_headers(user_id, "ComplianceOfficer")
