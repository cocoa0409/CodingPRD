"""Pre-built request headers for every actor the PRD admits.

Five of the seven roles are board staff whose ``X-User-ID`` is an opaque
identifier the API never resolves to a stored row. The remaining two,
``Licensee`` and ``Consumer``, are entity-backed: the identifier must be the
``id`` of a registered row, so those headers are built per test.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque board-staff identifiers. Reused across the suite so that
# segregation-of-duties assertions have stable, readable actors.
BOARD_ADMIN_USER_ID = "admin-01"
LICENSING_ANALYST_USER_ID = "analyst-01"
INVESTIGATOR_USER_ID = "inv-11"
SECOND_INVESTIGATOR_USER_ID = "inv-12"
HEARING_OFFICER_USER_ID = "ho-77"
SECOND_HEARING_OFFICER_USER_ID = "ho-78"
FUND_ADJUDICATOR_USER_ID = "fund-05"

TEST_USERS: dict[str, dict[str, str]] = {
    "board_admin_headers": build_user_headers(BOARD_ADMIN_USER_ID, Role.BOARD_ADMIN),
    "licensing_analyst_headers": build_user_headers(
        LICENSING_ANALYST_USER_ID, Role.LICENSING_ANALYST
    ),
    "investigator_headers": build_user_headers(INVESTIGATOR_USER_ID, Role.INVESTIGATOR),
    "second_investigator_headers": build_user_headers(
        SECOND_INVESTIGATOR_USER_ID, Role.INVESTIGATOR
    ),
    "hearing_officer_headers": build_user_headers(
        HEARING_OFFICER_USER_ID, Role.HEARING_OFFICER
    ),
    "second_hearing_officer_headers": build_user_headers(
        SECOND_HEARING_OFFICER_USER_ID, Role.HEARING_OFFICER
    ),
    "fund_adjudicator_headers": build_user_headers(
        FUND_ADJUDICATOR_USER_ID, Role.FUND_ADJUDICATOR
    ),
}

BOARD_ADMIN_HEADERS = TEST_USERS["board_admin_headers"]
LICENSING_ANALYST_HEADERS = TEST_USERS["licensing_analyst_headers"]
INVESTIGATOR_HEADERS = TEST_USERS["investigator_headers"]
SECOND_INVESTIGATOR_HEADERS = TEST_USERS["second_investigator_headers"]
HEARING_OFFICER_HEADERS = TEST_USERS["hearing_officer_headers"]
SECOND_HEARING_OFFICER_HEADERS = TEST_USERS["second_hearing_officer_headers"]
FUND_ADJUDICATOR_HEADERS = TEST_USERS["fund_adjudicator_headers"]


def make_licensee_headers(licensee_id: str) -> dict[str, str]:
    """Headers for a ``Licensee`` actor bound to a registered contracting entity."""
    return build_user_headers(licensee_id, Role.LICENSEE)


def make_consumer_headers(consumer_id: str) -> dict[str, str]:
    """Headers for a ``Consumer`` actor bound to a registered consumer row."""
    return build_user_headers(consumer_id, Role.CONSUMER)


def make_investigator_headers(user_id: str) -> dict[str, str]:
    """Headers for a specific investigator, for assigned-investigator checks."""
    return build_user_headers(user_id, Role.INVESTIGATOR)


def make_hearing_officer_headers(user_id: str) -> dict[str, str]:
    """Headers for a specific hearing officer, for presiding-officer checks."""
    return build_user_headers(user_id, Role.HEARING_OFFICER)


def make_analyst_headers(user_id: str) -> dict[str, str]:
    """Headers for a specific licensing analyst."""
    return build_user_headers(user_id, Role.LICENSING_ANALYST)
