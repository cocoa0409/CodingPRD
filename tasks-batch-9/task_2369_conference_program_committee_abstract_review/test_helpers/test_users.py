"""Pre-built role headers for every role the PRD declares.

ConferenceAdmin and PressOfficer are opaque identities: the shared constants
below are the canonical form for them. ProgramChair and Reviewer are backed by
a CommitteeMember row and Author is backed by an Author row, so ownership-gated
calls MUST use the per-instance builders with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque identities — the shared constant is the canonical form.
    "conference_admin_headers": build_user_headers(
        "test-conference-admin-1", "ConferenceAdmin"
    ),
    "press_officer_headers": build_user_headers("test-press-officer-1", "PressOfficer"),
    # Entity-backed identities — shared constants are only for calls that do not
    # resolve the caller to a stored row (for example a schema-rejection probe).
    "program_chair_headers": build_user_headers("test-program-chair-1", "ProgramChair"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "author_headers": build_user_headers("test-author-1", "Author"),
}


def make_program_chair_headers(member_id: str) -> dict:
    """ProgramChair headers for the CommitteeMember row with this id."""
    return build_user_headers(member_id, "ProgramChair")


def make_reviewer_headers(member_id: str) -> dict:
    """Reviewer headers for the CommitteeMember row with this id."""
    return build_user_headers(member_id, "Reviewer")


def make_author_headers(author_id: str) -> dict:
    """Author headers for the Author row with this id."""
    return build_user_headers(author_id, "Author")


def make_conference_admin_headers(user_id: str = "test-conference-admin-1") -> dict:
    """ConferenceAdmin headers; the identity is opaque so any id is accepted."""
    return build_user_headers(user_id, "ConferenceAdmin")


def make_press_officer_headers(user_id: str = "test-press-officer-1") -> dict:
    """PressOfficer headers; the identity is opaque so any id is accepted."""
    return build_user_headers(user_id, "PressOfficer")


ADMIN = TEST_USERS["conference_admin_headers"]
PRESS = TEST_USERS["press_officer_headers"]
