"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def facilities_headers():
    return TEST_USERS["facilities_headers"]


@pytest.fixture
def housekeeping_headers():
    return TEST_USERS["housekeeping_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def screening_headers():
    return TEST_USERS["screening_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]
