"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def dm_headers():
    return TEST_USERS["dm_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def ic_headers():
    return TEST_USERS["ic_headers"]


@pytest.fixture
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def buyer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def co_headers():
    return TEST_USERS["co_headers"]


@pytest.fixture
def ls_headers():
    return TEST_USERS["ls_headers"]
