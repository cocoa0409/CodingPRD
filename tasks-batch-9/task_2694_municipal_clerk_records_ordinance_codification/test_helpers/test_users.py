"""Pre-built auth headers for every role in PRD 2.1.

Six of the seven roles are opaque: any non-empty ``X-User-ID`` identifies the
actor and the API never resolves it to a stored row. ``Requester`` is the one
exception -- PRD 2.1 makes it entity-backed by ``PublicRecordsRequest``, so its
``X-User-ID`` must be the actual id of the request being acted on. Build those
headers with :func:`make_requester_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ANONYMOUS,
    ROLE_CITY_CLERK,
    ROLE_CODIFICATION_EDITOR,
    ROLE_DEPUTY_CLERK,
    ROLE_PRESIDING_OFFICER,
    ROLE_RECORDS_OFFICER,
    ROLE_REQUESTER,
)

# ---------------------------------------------------------------------------
# Opaque actor identifiers
# ---------------------------------------------------------------------------

CITY_CLERK_ID = "cc-01"
CITY_CLERK_ALT_ID = "cc-02"
DEPUTY_CLERK_ID = "dc-01"
DEPUTY_CLERK_ALT_ID = "dc-02"
PRESIDING_OFFICER_ID = "po-01"
RECORDS_OFFICER_ID = "ro-01"
RECORDS_OFFICER_ALT_ID = "ro-02"
CODIFICATION_EDITOR_ID = "ce-01"
CODIFICATION_EDITOR_ALT_ID = "ce-02"
CODIFICATION_EDITOR_THIRD_ID = "ce-05"
CODIFICATION_EDITOR_FOURTH_ID = "ce-06"
ANONYMOUS_ID = "anon-01"
ANONYMOUS_ALT_ID = "anon-02"

# ---------------------------------------------------------------------------
# Header bundles
# ---------------------------------------------------------------------------

CITY_CLERK = build_user_headers(CITY_CLERK_ID, ROLE_CITY_CLERK)
CITY_CLERK_ALT = build_user_headers(CITY_CLERK_ALT_ID, ROLE_CITY_CLERK)
DEPUTY_CLERK = build_user_headers(DEPUTY_CLERK_ID, ROLE_DEPUTY_CLERK)
DEPUTY_CLERK_ALT = build_user_headers(DEPUTY_CLERK_ALT_ID, ROLE_DEPUTY_CLERK)
PRESIDING_OFFICER = build_user_headers(PRESIDING_OFFICER_ID, ROLE_PRESIDING_OFFICER)
RECORDS_OFFICER = build_user_headers(RECORDS_OFFICER_ID, ROLE_RECORDS_OFFICER)
RECORDS_OFFICER_ALT = build_user_headers(RECORDS_OFFICER_ALT_ID, ROLE_RECORDS_OFFICER)
CODIFICATION_EDITOR = build_user_headers(CODIFICATION_EDITOR_ID, ROLE_CODIFICATION_EDITOR)
CODIFICATION_EDITOR_ALT = build_user_headers(
    CODIFICATION_EDITOR_ALT_ID, ROLE_CODIFICATION_EDITOR
)
CODIFICATION_EDITOR_THIRD = build_user_headers(
    CODIFICATION_EDITOR_THIRD_ID, ROLE_CODIFICATION_EDITOR
)
CODIFICATION_EDITOR_FOURTH = build_user_headers(
    CODIFICATION_EDITOR_FOURTH_ID, ROLE_CODIFICATION_EDITOR
)
ANONYMOUS = build_user_headers(ANONYMOUS_ID, ROLE_ANONYMOUS)
ANONYMOUS_ALT = build_user_headers(ANONYMOUS_ALT_ID, ROLE_ANONYMOUS)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "city_clerk": CITY_CLERK,
    "city_clerk_alt": CITY_CLERK_ALT,
    "deputy_clerk": DEPUTY_CLERK,
    "deputy_clerk_alt": DEPUTY_CLERK_ALT,
    "presiding_officer": PRESIDING_OFFICER,
    "records_officer": RECORDS_OFFICER,
    "records_officer_alt": RECORDS_OFFICER_ALT,
    "codification_editor": CODIFICATION_EDITOR,
    "codification_editor_alt": CODIFICATION_EDITOR_ALT,
    "codification_editor_third": CODIFICATION_EDITOR_THIRD,
    "codification_editor_fourth": CODIFICATION_EDITOR_FOURTH,
    "anonymous": ANONYMOUS,
    "anonymous_alt": ANONYMOUS_ALT,
}

# Every staff role, keyed by role name, for role-sweep parametrisation.
STAFF_HEADERS: Dict[str, Dict[str, str]] = {
    ROLE_CITY_CLERK: CITY_CLERK,
    ROLE_DEPUTY_CLERK: DEPUTY_CLERK,
    ROLE_PRESIDING_OFFICER: PRESIDING_OFFICER,
    ROLE_RECORDS_OFFICER: RECORDS_OFFICER,
    ROLE_CODIFICATION_EDITOR: CODIFICATION_EDITOR,
}

# A request whose two auth headers are absent altogether.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

# A syntactically valid pair naming a role outside the seven the PRD declares.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("mayor-01", "Mayor")


def make_requester_headers(request_id: str) -> Dict[str, str]:
    """Headers for the entity-backed ``Requester`` role.

    PRD 2.1 declares the ``Requester``'s credential to be the id of the
    ``PublicRecordsRequest`` itself, so ``X-User-ID`` must carry that id.
    """
    return build_user_headers(request_id, ROLE_REQUESTER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)
