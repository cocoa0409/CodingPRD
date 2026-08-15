"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def spo_headers():
    return TEST_USERS["spo_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def accountant_2_headers():
    return TEST_USERS["accountant_2_headers"]


@pytest.fixture
def accountant_9_headers():
    return TEST_USERS["accountant_9_headers"]


@pytest.fixture
def sponsor_official_headers():
    return TEST_USERS["sponsor_official_headers"]
