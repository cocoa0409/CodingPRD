"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def training_coordinator_headers():
    return TEST_USERS["training_coordinator_headers"]


@pytest.fixture
def crew_scheduler_headers():
    return TEST_USERS["crew_scheduler_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def check_airman_headers():
    # Shared fallback: only safe for tests that do not exercise identity checks.
    return TEST_USERS["check_airman_headers"]


@pytest.fixture
def pilot_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["pilot_headers"]
