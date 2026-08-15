"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ProvostOfficer, AppealOfficer, RecordsOfficer, SystemAdmin) use
shared constants: their X-User-ID is never compared to an entity id.

Entity-backed roles (Candidate, CommitteeChair, CommitteeVoter,
ExternalReviewer) MUST be built per instance with the actual entity id via the
make_*_headers builders whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership reads.
# "po_creator" is the case-creator identity used by fixtures; "po_decider" is
# the independent recording officer required by the decision SoD rule (PRD §3.7).
TEST_USERS = {
    "provost_creator_headers": build_user_headers("po_creator", "ProvostOfficer"),
    "provost_decider_headers": build_user_headers("po_decider", "ProvostOfficer"),
    "provost_other_headers": build_user_headers("po_other", "ProvostOfficer"),
    "appeal_officer_headers": build_user_headers("appeal_officer_1", "AppealOfficer"),
    "records_officer_headers": build_user_headers("records_officer_1", "RecordsOfficer"),
    "system_admin_headers": build_user_headers("sysadmin_1", "SystemAdmin"),
    # Generic authenticated reader for the Any-covered GET endpoints.
    "reader_headers": build_user_headers("reader_1", "ProvostOfficer"),
}


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (identity: the Candidate entity id). Pass the owning
    candidate's id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Candidate")


def make_committee_chair_headers(member_id: str) -> dict:
    """For CommitteeChair (identity: the CommitteeMember entity id). Pass the
    chair member's id for round open/close-voting/certify/reopen."""
    return build_user_headers(member_id, "CommitteeChair")


def make_committee_voter_headers(member_id: str) -> dict:
    """For CommitteeVoter (identity: the CommitteeMember entity id). Pass the
    voting member's id for cast/patch/retract."""
    return build_user_headers(member_id, "CommitteeVoter")


def make_external_reviewer_headers(reviewer_id: str) -> dict:
    """For ExternalReviewer (identity: the ExternalReviewer entity id). Pass the
    invited reviewer's id for accept/decline/submit-letter."""
    return build_user_headers(reviewer_id, "ExternalReviewer")
