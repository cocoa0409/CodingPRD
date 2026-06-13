"""Pre-built role headers for every role in the PRD (§2.1).

FoundationAdmin and DisbursementOfficer carry opaque X-User-ID values not tied
to any entity. Applicant and CommitteeMember are entity-backed: ownership checks
compare X-User-ID to the resource's applicant_id / committee_member_id, so
ownership-gated calls MUST use the per-instance builders below with the real
entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (e.g. 400-on-bad-payload, 404-on-missing-resource, role-forbidden).
TEST_USERS = {
    "foundation_admin_headers": build_user_headers("test-admin-1", "FoundationAdmin"),
    "disbursement_officer_headers": build_user_headers("test-officer-1", "DisbursementOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "committee_member_headers": build_user_headers("test-member-1", "CommitteeMember"),
}


# Opaque-role builders (X-User-ID is not compared to any entity id).
def make_foundation_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "FoundationAdmin")


def make_disbursement_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "DisbursementOfficer")


# Per-instance builders — required for every entity_backed role.
def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the actual Applicant.id as
    user_id whenever the call is ownership-gated (submit/withdraw own application,
    acknowledge own stewardship, create own child resources)."""
    return build_user_headers(user_id, "Applicant")


def make_committee_member_headers(user_id: str) -> dict:
    """For CommitteeMember (entity_backed:CommitteeMember). Pass the actual
    CommitteeMember.id as user_id whenever the call is ownership-gated (submit own
    score, decline own assignment, create own score)."""
    return build_user_headers(user_id, "CommitteeMember")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for arbitrary (role, user_id) pairs, including invalid roles."""
    return build_user_headers(user_id, role)
