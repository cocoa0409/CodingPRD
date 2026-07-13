"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def shift_lead_headers():
    return TEST_USERS["shift_lead_headers"]


@pytest.fixture
def scooper_headers():
    return TEST_USERS["scooper_headers"]


@pytest.fixture
def baker_headers():
    return TEST_USERS["baker_headers"]
