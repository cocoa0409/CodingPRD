"""Pre-built identity headers for every role named by the PRD.

All five roles carry opaque identity: the ``X-User-ID`` value is an arbitrary
caller token that is never matched against any stored record. Distinct token
values still matter, because the PRD's segregation-of-duties rules compare the
caller's ``X-User-ID`` with the user id recorded on the subject record.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Canonical caller tokens
# ---------------------------------------------------------------------------
PLANNER_USER_ID = "planner-1"
SECOND_PLANNER_USER_ID = "planner-2"
COORDINATOR_USER_ID = "coord-1"
BOARD_USER_ID = "board-1"
SECOND_BOARD_USER_ID = "board-2"
OFFICER_USER_ID = "officer-1"
SECOND_OFFICER_USER_ID = "officer-2"
GUARDIAN_USER_ID = "guardian-1"


TEST_USERS = {
    "planner_headers": build_user_headers(
        PLANNER_USER_ID, UserRole.DISTRICT_PLANNER.value
    ),
    "second_planner_headers": build_user_headers(
        SECOND_PLANNER_USER_ID, UserRole.DISTRICT_PLANNER.value
    ),
    "coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, UserRole.ENGAGEMENT_COORDINATOR.value
    ),
    "board_headers": build_user_headers(BOARD_USER_ID, UserRole.BOARD_MEMBER.value),
    "second_board_headers": build_user_headers(
        SECOND_BOARD_USER_ID, UserRole.BOARD_MEMBER.value
    ),
    "officer_headers": build_user_headers(
        OFFICER_USER_ID, UserRole.TRANSFER_OFFICER.value
    ),
    "second_officer_headers": build_user_headers(
        SECOND_OFFICER_USER_ID, UserRole.TRANSFER_OFFICER.value
    ),
    "guardian_headers": build_user_headers(GUARDIAN_USER_ID, UserRole.GUARDIAN.value),
}


# ---------------------------------------------------------------------------
# Per-caller builders — use these whenever a test needs a specific token,
# for example to make the caller differ from the record's recorded author.
# ---------------------------------------------------------------------------
def make_planner_headers(user_id: str) -> dict:
    """Headers for a DistrictPlanner caller identified by ``user_id``."""
    return build_user_headers(user_id, UserRole.DISTRICT_PLANNER.value)


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for an EngagementCoordinator caller identified by ``user_id``."""
    return build_user_headers(user_id, UserRole.ENGAGEMENT_COORDINATOR.value)


def make_board_headers(user_id: str) -> dict:
    """Headers for a BoardMember caller identified by ``user_id``."""
    return build_user_headers(user_id, UserRole.BOARD_MEMBER.value)


def make_officer_headers(user_id: str) -> dict:
    """Headers for a TransferOfficer caller identified by ``user_id``."""
    return build_user_headers(user_id, UserRole.TRANSFER_OFFICER.value)


def make_guardian_headers(user_id: str) -> dict:
    """Headers for a Guardian caller identified by ``user_id``."""
    return build_user_headers(user_id, UserRole.GUARDIAN.value)


ALL_ROLE_HEADERS = {
    UserRole.DISTRICT_PLANNER.value: TEST_USERS["planner_headers"],
    UserRole.ENGAGEMENT_COORDINATOR.value: TEST_USERS["coordinator_headers"],
    UserRole.BOARD_MEMBER.value: TEST_USERS["board_headers"],
    UserRole.TRANSFER_OFFICER.value: TEST_USERS["officer_headers"],
    UserRole.GUARDIAN.value: TEST_USERS["guardian_headers"],
}
"""Every role mapped to one representative header set."""
