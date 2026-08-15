"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coop_admin_headers():
    return TEST_USERS["coop_admin_headers"]


@pytest.fixture
def grower_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["grower_headers"]


@pytest.fixture
def field_officer_headers():
    return TEST_USERS["field_officer_headers"]


@pytest.fixture
def station_operator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["station_operator_headers"]


@pytest.fixture
def pool_manager_headers():
    return TEST_USERS["pool_manager_headers"]
