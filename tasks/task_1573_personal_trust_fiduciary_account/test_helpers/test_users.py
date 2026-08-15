"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (TrustOfficer, TrustExecutive, InvestmentManager,
TrustOperationsOfficer, TaxSpecialist) use shared constants: their X-User-ID
is never compared to an entity id.

Entity-backed roles (CommitteeMember, Beneficiary) MUST use the per-instance
builders with the real entity id whenever the call is ownership-gated; the
shared constants exist only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "officer_headers": build_user_headers("officer-1", "TrustOfficer"),
    "executive_headers": build_user_headers("exec-1", "TrustExecutive"),
    "manager_headers": build_user_headers("manager-1", "InvestmentManager"),
    "ops_headers": build_user_headers("ops-1", "TrustOperationsOfficer"),
    "tax_headers": build_user_headers("tax-1", "TaxSpecialist"),
    # Entity-backed fallbacks: safe ONLY where ownership is not exercised.
    "committee_headers": build_user_headers("test-committee-1", "CommitteeMember"),
    "beneficiary_headers": build_user_headers("test-beneficiary-1", "Beneficiary"),
}


def make_officer_headers(user_id: str) -> dict:
    """TrustOfficer with a specific opaque user id (e.g. for SoD pairing)."""
    return build_user_headers(user_id, "TrustOfficer")


def make_executive_headers(user_id: str) -> dict:
    """TrustExecutive with a specific opaque user id."""
    return build_user_headers(user_id, "TrustExecutive")


def make_manager_headers(user_id: str) -> dict:
    """InvestmentManager with a specific opaque user id."""
    return build_user_headers(user_id, "InvestmentManager")


def make_ops_headers(user_id: str) -> dict:
    """TrustOperationsOfficer with a specific opaque user id (fee disclose/post SoD)."""
    return build_user_headers(user_id, "TrustOperationsOfficer")


def make_tax_headers(user_id: str) -> dict:
    """TaxSpecialist with a specific opaque user id (prepare/review SoD)."""
    return build_user_headers(user_id, "TaxSpecialist")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember (entity-backed). Pass the actual CommitteeMember.id as
    user_id — the server records it as committee_member_id on each vote."""
    return build_user_headers(user_id, "CommitteeMember")


def make_beneficiary_headers(user_id: str) -> dict:
    """Beneficiary (entity-backed). Pass the actual Beneficiary.id as user_id
    whenever the call is ownership-gated (own requests, own trust's statements
    and fee assessments)."""
    return build_user_headers(user_id, "Beneficiary")
