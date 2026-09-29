"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. For every role other than Member the PRD says
# X-User-ID is an opaque operator identifier not tied to any persisted entity.
PROGRAMMER_USER_ID = "u-prog-1"
RIGHTS_MANAGER_USER_ID = "u-rm-1"
RIGHTS_MANAGER_TWO_USER_ID = "u-rm-2"
TECHNICAL_MANAGER_USER_ID = "u-tech-1"
BOX_OFFICE_USER_ID = "u-box-1"
EXECUTIVE_DIRECTOR_USER_ID = "u-ed-1"
EXECUTIVE_DIRECTOR_TWO_USER_ID = "u-ed-2"

# An anonymous walk-up caller sends no X-User-Role header at all.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}

TEST_USERS = {
    "programmer_headers": build_user_headers(PROGRAMMER_USER_ID, "Programmer"),
    "rights_manager_headers": build_user_headers(
        RIGHTS_MANAGER_USER_ID, "RightsManager"
    ),
    # A second rights manager: clearing a licence must be done by a different
    # X-User-ID from the one that lodged it.
    "rights_manager_two_headers": build_user_headers(
        RIGHTS_MANAGER_TWO_USER_ID, "RightsManager"
    ),
    "technical_manager_headers": build_user_headers(
        TECHNICAL_MANAGER_USER_ID, "TechnicalManager"
    ),
    "box_office_headers": build_user_headers(BOX_OFFICE_USER_ID, "BoxOfficeManager"),
    "executive_director_headers": build_user_headers(
        EXECUTIVE_DIRECTOR_USER_ID, "ExecutiveDirector"
    ),
    "executive_director_two_headers": build_user_headers(
        EXECUTIVE_DIRECTOR_TWO_USER_ID, "ExecutiveDirector"
    ),
    # Member is identified by the id of the acting membership record, so this
    # shared constant is only safe for tests that never exercise ownership.
    "member_headers": build_user_headers("u-member-1", "Member"),
    "anonymous_headers": ANONYMOUS_HEADERS,
}


def make_member_headers(member_id: str) -> dict:
    """Headers for a Member acting on their own behalf.

    When X-User-Role is Member, X-User-ID is the id of the acting Member, so
    every ownership-gated call must pass the real membership record's id.
    """
    return build_user_headers(member_id, "Member")


def make_programmer_headers(user_id: str = PROGRAMMER_USER_ID) -> dict:
    return build_user_headers(user_id, "Programmer")


def make_rights_manager_headers(user_id: str = RIGHTS_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "RightsManager")


def make_technical_manager_headers(user_id: str = TECHNICAL_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "TechnicalManager")


def make_box_office_headers(user_id: str = BOX_OFFICE_USER_ID) -> dict:
    return build_user_headers(user_id, "BoxOfficeManager")


def make_executive_director_headers(
    user_id: str = EXECUTIVE_DIRECTOR_USER_ID,
) -> dict:
    return build_user_headers(user_id, "ExecutiveDirector")


def make_role_headers(role: str, user_id: str = "u-operator-1") -> dict:
    """Headers for an arbitrary role name, including undeclared ones."""
    return build_user_headers(user_id, role)
