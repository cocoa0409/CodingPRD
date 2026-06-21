"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def studio_admin_headers():
    return TEST_USERS["studio_admin_headers"]


@pytest.fixture
def booking_agent_headers():
    return TEST_USERS["booking_agent_headers"]


@pytest.fixture
def performer_headers():
    return TEST_USERS["performer_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
