"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def vet():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def billing():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def farrier_role():
    """Shared Farrier headers — only for calls that run no ownership check."""
    return TEST_USERS["farrier_headers"]


@pytest.fixture
def client_role():
    """Shared ClientUser headers — only for calls that run no ownership check."""
    return TEST_USERS["client_user_headers"]


@pytest.fixture
def no_auth():
    return NO_AUTH_HEADERS
