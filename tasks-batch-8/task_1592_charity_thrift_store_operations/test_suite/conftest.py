"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def intake_attendant_headers():
    return TEST_USERS["intake_attendant_headers"]


@pytest.fixture
def pricer_headers():
    return TEST_USERS["pricer_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def cashier_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def driver_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["driver_headers"]


@pytest.fixture
def volunteer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["volunteer_headers"]
