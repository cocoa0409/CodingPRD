"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def tour_manager_2_headers():
    return TEST_USERS["tour_manager_2_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def accountant_2_headers():
    return TEST_USERS["accountant_2_headers"]


@pytest.fixture
def venue_rep_headers():
    return TEST_USERS["venue_rep_headers"]


@pytest.fixture
def seller_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["seller_headers"]
