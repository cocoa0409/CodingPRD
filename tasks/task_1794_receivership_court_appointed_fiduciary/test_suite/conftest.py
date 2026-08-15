"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def court_headers():
    return TEST_USERS["court_headers"]


@pytest.fixture
def receiver_headers():
    return TEST_USERS["receiver_headers"]


@pytest.fixture
def creditor_headers():
    return TEST_USERS["creditor_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
