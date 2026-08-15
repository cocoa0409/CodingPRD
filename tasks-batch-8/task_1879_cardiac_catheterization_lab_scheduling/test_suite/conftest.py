"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def cardiologist_headers():
    return TEST_USERS["cardiologist_headers"]


@pytest.fixture
def technologist_headers():
    return TEST_USERS["technologist_headers"]


@pytest.fixture
def nurse_manager_headers():
    return TEST_USERS["nurse_manager_headers"]


@pytest.fixture
def registry_coordinator_headers():
    return TEST_USERS["registry_coordinator_headers"]
