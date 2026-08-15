"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def exchange_admin_headers():
    return TEST_USERS["exchange_admin_headers"]


@pytest.fixture
def demand_side_headers():
    return TEST_USERS["demand_side_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def publisher_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["publisher_manager_headers"]
