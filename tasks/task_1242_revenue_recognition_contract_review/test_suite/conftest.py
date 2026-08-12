"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
