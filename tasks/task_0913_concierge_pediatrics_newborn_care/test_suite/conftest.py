"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def physician_headers():
    """Unbound Physician identity — only for calls that never reach ownership."""
    return TEST_USERS["physician_headers"]


@pytest.fixture
def parent_headers():
    """Unbound Parent identity — only for calls that never reach ownership."""
    return TEST_USERS["parent_headers"]
