"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """ClubAdmin — opaque identity (PRD §2.1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def member_headers():
    """Member with a placeholder id. Only safe where no ownership check is reached;
    ownership-gated calls must use make_member_headers(member["id"])."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def no_auth_headers():
    """No X-User-ID and no X-User-Role at all (PRD §2.1)."""
    return NO_AUTH_HEADERS
