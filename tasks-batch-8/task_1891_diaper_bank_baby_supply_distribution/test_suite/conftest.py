"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def bank_admin_headers():
    return TEST_USERS["bank_admin_headers"]


@pytest.fixture
def warehouse_manager_headers():
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def agency_coordinator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["agency_coordinator_headers"]
