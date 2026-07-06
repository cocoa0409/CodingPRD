"""Authentication and role-based authorization (queue B: rbac)."""
from test_helpers import (
    TEST_USERS, ANONYMOUS_HEADERS,
    validate_error, ApiErrorId,
    create_election_payload,
    create_election, create_place,
)

ADMIN = TEST_USERS["election_admin_headers"]
POLL_WORKER = TEST_USERS["poll_worker_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def test_poll_worker_cannot_create_election(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/poll_worker_cannot_create_election_unauthorized
    """
    resp = api.create_election(create_election_payload(), POLL_WORKER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_support_agent_cannot_open_place(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/support_agent_cannot_open_place_unauthorized
    """
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"])
    resp = api.open_place(pp["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_request_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_returns_401
    """
    resp = api.create_election(create_election_payload(), ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
