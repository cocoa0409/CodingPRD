"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def patient_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["patient_headers"]


@pytest.fixture
def triage_nurse_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["triage_nurse_headers"]


@pytest.fixture
def front_desk_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def provider_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["provider_headers"]


@pytest.fixture
def billing_specialist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["billing_specialist_headers"]
