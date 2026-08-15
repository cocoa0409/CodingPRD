"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def captain_headers():
    return TEST_USERS["captain_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def charter_agent_headers():
    return TEST_USERS["charter_agent_headers"]


@pytest.fixture
def galley_manager_headers():
    return TEST_USERS["galley_manager_headers"]


@pytest.fixture
def dock_attendant_headers():
    return TEST_USERS["dock_attendant_headers"]
