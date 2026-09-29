"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def district_coordinator_headers():
    return TEST_USERS["district_coordinator_headers"]


@pytest.fixture
def school_coordinator_headers():
    return TEST_USERS["school_coordinator_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]
