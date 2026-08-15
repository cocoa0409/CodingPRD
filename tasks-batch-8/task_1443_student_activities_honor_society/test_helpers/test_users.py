"""Pre-built role headers for every role in the PRD.

PRD section 2.1: ActivitiesDirector and Advisor X-User-ID values are opaque
operator identifiers never compared to any entity id, so shared constants are
canonical for them. Officer and Member are entity-backed: X-User-ID is the id
of the acting Member, so ownership-gated calls (voting, withdrawal, appeal,
resignation, officer-authored minutes and fundraisers) MUST be made with
make_officer_headers(member_id) / make_member_headers(member_id).
"""
from prd_bench_local_runner.testing import build_user_headers

ADVISOR_USER_ID = "adv-1"
DIRECTOR_USER_ID = "dir-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "advisor_headers": build_user_headers(ADVISOR_USER_ID, "Advisor"),
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "ActivitiesDirector"),
    # Entity-backed roles: shared constants are a fallback for tests that do
    # NOT exercise ownership (e.g., role-denial checks).
    "officer_headers": build_user_headers("officer-nonowner", "Officer"),
    "member_headers": build_user_headers("member-nonowner", "Member"),
}


def make_advisor_headers(user_id: str) -> dict:
    """Advisor is opaque; use a pinned id when the workflow records it
    (e.g., segregation-of-duties comparisons on fundraiser approval)."""
    return build_user_headers(user_id, "Advisor")


def make_director_headers(user_id: str) -> dict:
    """ActivitiesDirector is opaque; pin the id for segregation-of-duties."""
    return build_user_headers(user_id, "ActivitiesDirector")


def make_officer_headers(member_id: str) -> dict:
    """Officer is entity-backed: pass the acting Member.id as user_id."""
    return build_user_headers(member_id, "Officer")


def make_member_headers(member_id: str) -> dict:
    """Member is entity-backed: pass the acting Member.id as user_id."""
    return build_user_headers(member_id, "Member")
