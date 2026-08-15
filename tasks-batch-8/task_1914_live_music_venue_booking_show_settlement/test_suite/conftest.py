"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def venue_manager_headers():
    return TEST_USERS["venue_manager_headers"]


@pytest.fixture
def booking_agent_headers():
    return TEST_USERS["booking_agent_headers"]


@pytest.fixture
def promoter_headers():
    return TEST_USERS["promoter_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]
