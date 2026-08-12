"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    FINANCE_POSTER_HEADERS,
    FINANCE_PREPARER_HEADERS,
    FINANCE_SECOND_PREPARER_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_preparer_headers():
    return FINANCE_PREPARER_HEADERS


@pytest.fixture
def finance_poster_headers():
    return FINANCE_POSTER_HEADERS


@pytest.fixture
def finance_second_preparer_headers():
    return FINANCE_SECOND_PREPARER_HEADERS
