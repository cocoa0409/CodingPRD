"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def queue_admin_headers():
    return TEST_USERS["queue_admin_headers"]


@pytest.fixture
def study_engineer_headers():
    return TEST_USERS["study_engineer_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
