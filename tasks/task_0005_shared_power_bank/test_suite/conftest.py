"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    OPERATOR_2_HEADERS,
    OPERATOR_HEADERS,
    PARTNER_HEADERS_PLACEHOLDER,
    USER_HEADERS_PLACEHOLDER,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset the server's in-memory state before every test so each test
    starts from an empty universe (PRD test endpoints — auth-exempt)."""
    api_client.session.post(f"{api_client.base_url}/_state/reset", json={}, timeout=5)
    yield


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def operator_headers():
    return OPERATOR_HEADERS


@pytest.fixture
def operator2_headers():
    return OPERATOR_2_HEADERS


@pytest.fixture
def user_headers_placeholder():
    """Headers for the User role pointing at a NON-EXISTENT user id.

    Use this only for tests that exercise gates that fire BEFORE any
    ownership compare (auth-missing, 404-on-resource-missing, role-permitted-
    but-wrong-resource). Tests that exercise an ownership-gated path MUST
    create a real User and use ``make_user_headers(user["id"])``.
    """
    return USER_HEADERS_PLACEHOLDER


@pytest.fixture
def partner_headers_placeholder():
    return PARTNER_HEADERS_PLACEHOLDER


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
