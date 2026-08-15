"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def broker_principal_headers():
    return TEST_USERS["broker_principal_headers"]


@pytest.fixture
def listing_agent_headers():
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def buyer_agent_headers():
    return TEST_USERS["buyer_agent_headers"]


@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def facility_scheduler_headers():
    return TEST_USERS["facility_scheduler_headers"]
