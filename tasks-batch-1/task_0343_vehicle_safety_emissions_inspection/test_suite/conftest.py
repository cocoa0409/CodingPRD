"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def station_manager_headers():
    return TEST_USERS["station_manager_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def state_auditor_headers():
    return TEST_USERS["state_auditor_headers"]
