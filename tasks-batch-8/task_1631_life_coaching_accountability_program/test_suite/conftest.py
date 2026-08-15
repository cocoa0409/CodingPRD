"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def practice_manager_headers():
    return TEST_USERS["practice_manager_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
