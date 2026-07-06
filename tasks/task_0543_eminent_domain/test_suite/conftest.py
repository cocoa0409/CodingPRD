"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANON_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def right_of_way_agent_headers():
    return TEST_USERS["right_of_way_agent_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def property_owner_headers():
    return TEST_USERS["property_owner_headers"]


@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def utility_coordinator_headers():
    return TEST_USERS["utility_coordinator_headers"]


@pytest.fixture
def anon_headers():
    return ANON_HEADERS
