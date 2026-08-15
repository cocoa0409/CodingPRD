"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def terminal_admin_headers():
    return TEST_USERS["terminal_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def dock_supervisor_headers():
    return TEST_USERS["dock_supervisor_headers"]


@pytest.fixture
def rating_clerk_headers():
    return TEST_USERS["rating_clerk_headers"]


@pytest.fixture
def osd_clerk_headers():
    return TEST_USERS["osd_clerk_headers"]
