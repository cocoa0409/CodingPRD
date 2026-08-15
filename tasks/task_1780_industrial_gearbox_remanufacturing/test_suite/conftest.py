"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def reman_engineer_headers():
    return TEST_USERS["reman_engineer_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def customer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_headers"]
