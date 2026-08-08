"""Pytest fixtures exposing the transitional-care test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def care_navigator_headers():
    return TEST_USERS["care_navigator_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]
