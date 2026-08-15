"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def officer_1_headers():
    return TEST_USERS["officer_1_headers"]


@pytest.fixture
def officer_2_headers():
    return TEST_USERS["officer_2_headers"]


@pytest.fixture
def barn_manager_headers():
    return TEST_USERS["barn_manager_headers"]


@pytest.fixture
def vol_coordinator_headers():
    return TEST_USERS["vol_coordinator_headers"]
