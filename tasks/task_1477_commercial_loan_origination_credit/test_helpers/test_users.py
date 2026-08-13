"""Pre-built role headers for every role in the PRD.

BankAdmin is an opaque identity (X-User-ID is never compared to any entity id),
so a shared constant is canonical. Every other role is entity-backed: X-User-ID
must be the id of a registered BankOfficer, so per-instance builders are
mandatory for ownership- or segregation-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "bank_admin_headers": build_user_headers("test-bank-admin-1", "BankAdmin"),
}


def make_relationship_manager_headers(user_id: str) -> dict:
    """RelationshipManager is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "RelationshipManager")


def make_credit_analyst_headers(user_id: str) -> dict:
    """CreditAnalyst is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "CreditAnalyst")


def make_appraisal_manager_headers(user_id: str) -> dict:
    """AppraisalManager is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "AppraisalManager")


def make_committee_chair_headers(user_id: str) -> dict:
    """CommitteeChair is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "CommitteeChair")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "CommitteeMember")


def make_credit_policy_officer_headers(user_id: str) -> dict:
    """CreditPolicyOfficer is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "CreditPolicyOfficer")


def make_credit_administrator_headers(user_id: str) -> dict:
    """CreditAdministrator is entity-backed: pass the BankOfficer.id."""
    return build_user_headers(user_id, "CreditAdministrator")
