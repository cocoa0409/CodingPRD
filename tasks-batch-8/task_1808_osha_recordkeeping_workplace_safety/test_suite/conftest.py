"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def recordkeeping_coordinator_headers():
    return TEST_USERS["recordkeeping_coordinator_headers"]


@pytest.fixture
def investigating_supervisor_headers():
    return TEST_USERS["investigating_supervisor_headers"]
