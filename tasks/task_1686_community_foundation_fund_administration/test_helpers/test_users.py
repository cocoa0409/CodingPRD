"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (FoundationAdmin, GiftOfficer, ComplianceOfficer, FinanceOfficer,
ProgramOfficer, InvestmentManager) use opaque X-User-ID values — the server
never compares them to entity rows, only against each other for
segregation-of-duties checks.

Entity-backed roles (Advisor -> FundAdvisor.id, Applicant ->
ScholarshipApplication.id, CommitteeMember -> CommitteeMember.id) MUST use the
per-instance builders below whenever the call is ownership-gated; the shared
constants are safe only for calls whose success does not depend on identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "foundation_admin_headers": build_user_headers("admin-1", "FoundationAdmin"),
    "gift_officer_headers": build_user_headers("gift-1", "GiftOfficer"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "finance_officer_headers": build_user_headers("fo-1", "FinanceOfficer"),
    "program_officer_headers": build_user_headers("po-1", "ProgramOfficer"),
    "investment_manager_headers": build_user_headers("im-1", "InvestmentManager"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership
    # calls only (e.g. submitting a brand-new application).
    "advisor_headers": build_user_headers("advisor-unowned", "Advisor"),
    "applicant_headers": build_user_headers("applicant-unowned", "Applicant"),
    "committee_member_headers": build_user_headers("member-unowned", "CommitteeMember"),
}


def make_officer_headers(role: str, user_id: str) -> dict:
    """Headers for a staff role with a caller-chosen opaque user id.

    Use distinct ids to satisfy segregation-of-duties rules (e.g. claimer
    'co-1' vs approver 'co-2'), or a deliberately equal id to violate them.
    """
    return build_user_headers(user_id, role)


def make_advisor_headers(advisor_id: str) -> dict:
    """Advisor is entity-backed by FundAdvisor.id — pass the advisor row's id."""
    return build_user_headers(advisor_id, "Advisor")


def make_applicant_headers(application_id: str) -> dict:
    """Applicant is entity-backed by ScholarshipApplication.id."""
    return build_user_headers(application_id, "Applicant")


def make_committee_member_headers(member_id: str) -> dict:
    """CommitteeMember is entity-backed by CommitteeMember.id."""
    return build_user_headers(member_id, "CommitteeMember")
