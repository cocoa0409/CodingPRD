"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def comp_admin_headers():
    return TEST_USERS["comp_admin_headers"]


@pytest.fixture
def comp_admin_alt_headers():
    return TEST_USERS["comp_admin_alt_headers"]


@pytest.fixture
def comp_analyst_headers():
    return TEST_USERS["comp_analyst_headers"]


@pytest.fixture
def comp_manager_headers():
    return TEST_USERS["comp_manager_headers"]


@pytest.fixture
def rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["rep_headers"]
