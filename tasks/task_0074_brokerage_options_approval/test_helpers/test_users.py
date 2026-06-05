"""Pre-built role headers for every role in the PRD.

All three roles use opaque identity (X-User-ID is never matched against an
entity id), so the shared constants below are the canonical form. The optional
per-instance builders thread a chosen opaque id when a test needs to control it
(e.g. distinct submitter vs approver for segregation of duties).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_holder_headers": build_user_headers("h_a", "AccountHolder"),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "custodian_headers": build_user_headers("cust_1", "Custodian"),
}


def make_account_holder_headers(user_id: str) -> dict:
    """AccountHolder headers bound to a specific opaque X-User-ID."""
    return build_user_headers(user_id, "AccountHolder")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers bound to a specific opaque X-User-ID.

    Use distinct ids for the submitter and the decider to satisfy
    segregation of duties (or the same id to violate it deliberately).
    """
    return build_user_headers(user_id, "ComplianceOfficer")


def make_custodian_headers(user_id: str) -> dict:
    """Custodian headers bound to a specific opaque X-User-ID."""
    return build_user_headers(user_id, "Custodian")
