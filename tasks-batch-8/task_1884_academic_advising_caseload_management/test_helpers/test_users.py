"""Pre-built role headers for the four PRD roles (§2.1).

Advisor is entity-backed: when the role is Advisor, X-User-ID must be the acting
Advisor resource's id because ownership checks compare resource advisor_id fields
to X-User-ID (PRD §2.1). Use make_advisor_headers(advisor["id"]) for any
ownership-gated call; the shared "advisor_headers" constant is only a fallback
for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is not tied to any persisted entity.
    "director_headers": build_user_headers("test-director-1", "AdvisingDirector"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDeskStaff"),
    "faculty_headers": build_user_headers("test-faculty-1", "FacultyReferrer"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
}


def make_advisor_headers(advisor_id: str) -> dict:
    """Headers for the Advisor role. Pass the actual Advisor.id whenever the call
    is ownership-gated (outreach, interventions, plan writes, hold release,
    appointment complete, CONFIDENTIAL notes, call-next)."""
    return build_user_headers(advisor_id, "Advisor")


def make_ghost_headers(user_id: str = "test-ghost-1", role: str = "GhostRole") -> dict:
    """Headers carrying a role value outside the four declared roles (PRD §2.1)."""
    return build_user_headers(user_id, role)
