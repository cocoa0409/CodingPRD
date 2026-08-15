"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "insider_headers": build_user_headers("test-insider-1", "Insider"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "committee_member_headers": build_user_headers("test-member-1", "CommitteeMember"),
    # opaque role: shared constant is the canonical form.
    "legal_admin_headers": build_user_headers("test-legal-admin-1", "LegalAdmin"),
}


# Per-instance builders — required for every entity_backed role (PRD §2.1: when the
# role is Insider / ComplianceOfficer / CommitteeMember, X-User-ID is the id of the
# acting CoveredPerson record).
def make_insider_headers(user_id: str) -> dict:
    """For Insider calls. Pass the acting CoveredPerson's id whenever the call is
    ownership-gated (own preclearance/exception/plan/attestation)."""
    return build_user_headers(user_id, "Insider")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer calls. Pass the officer's own CoveredPerson id —
    segregation-of-duties checks compare it against the resource owner."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_committee_member_headers(user_id: str) -> dict:
    """For CommitteeMember calls. Pass the member's CoveredPerson id — it is recorded
    on the exception request's voter roll."""
    return build_user_headers(user_id, "CommitteeMember")


def make_legal_admin_headers(user_id: str = "test-legal-admin-1") -> dict:
    """For LegalAdmin calls. X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "LegalAdmin")
