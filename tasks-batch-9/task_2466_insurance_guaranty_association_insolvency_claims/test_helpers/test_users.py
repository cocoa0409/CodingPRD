"""Pre-built role headers for every role in the PRD.

Two of the eight roles are backed by a stored row rather than an opaque string:
a ClaimsAdjuster or DefenseCounsel presents the id of its vendor engagement, and
a MemberInsurerAgent presents the id of its member insurer. For those roles the
per-instance builders below MUST be used with the real row id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COMMITTEE_OFFICER_USER_ID,
    SCREENING_ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
)

# Shared constants — safe for the opaque roles and for calls that never test
# ownership (bad payloads, unknown ids, role-permission denials).
TEST_USERS = {
    "association_admin_headers": build_user_headers("admin-1", "AssociationAdmin"),
    "receiver_liaison_headers": build_user_headers("receiver-1", "ReceiverLiaison"),
    "coverage_analyst_headers": build_user_headers(
        SCREENING_ANALYST_USER_ID, "CoverageAnalyst"
    ),
    "second_coverage_analyst_headers": build_user_headers(
        SECOND_ANALYST_USER_ID, "CoverageAnalyst"
    ),
    "claims_committee_officer_headers": build_user_headers(
        COMMITTEE_OFFICER_USER_ID, "ClaimsCommitteeOfficer"
    ),
    "assessment_officer_headers": build_user_headers("officer-assess-1", "AssessmentOfficer"),
    # Fallbacks for the two entity-backed vendor roles and the member agent —
    # only valid where the call is not ownership-gated.
    "claims_adjuster_headers": build_user_headers("adjuster-unassigned", "ClaimsAdjuster"),
    "defense_counsel_headers": build_user_headers("counsel-unassigned", "DefenseCounsel"),
    "member_insurer_agent_headers": build_user_headers("member-unassessed", "MemberInsurerAgent"),
}


def make_association_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "AssociationAdmin")


def make_receiver_liaison_headers(user_id: str = "receiver-1") -> dict:
    return build_user_headers(user_id, "ReceiverLiaison")


def make_coverage_analyst_headers(user_id: str = SCREENING_ANALYST_USER_ID) -> dict:
    """The screening analyst's X-User-ID is recorded on the claim it screens."""
    return build_user_headers(user_id, "CoverageAnalyst")


def make_claims_committee_officer_headers(user_id: str = COMMITTEE_OFFICER_USER_ID) -> dict:
    """The approving officer's X-User-ID is recorded on the claim it approves."""
    return build_user_headers(user_id, "ClaimsCommitteeOfficer")


def make_assessment_officer_headers(user_id: str = "officer-assess-1") -> dict:
    return build_user_headers(user_id, "AssessmentOfficer")


def make_claims_adjuster_headers(vendor_assignment_id: str) -> dict:
    """For a ClaimsAdjuster: X-User-ID is the id of its ADJUSTER engagement."""
    return build_user_headers(vendor_assignment_id, "ClaimsAdjuster")


def make_defense_counsel_headers(vendor_assignment_id: str) -> dict:
    """For a DefenseCounsel: X-User-ID is the id of its DEFENSE_COUNSEL engagement."""
    return build_user_headers(vendor_assignment_id, "DefenseCounsel")


def make_member_insurer_agent_headers(member_insurer_id: str) -> dict:
    """For a MemberInsurerAgent: X-User-ID equals the MemberInsurer id."""
    return build_user_headers(member_insurer_id, "MemberInsurerAgent")


def headers_without_role(user_id: str = "admin-1") -> dict:
    """Auth headers with the role header omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
