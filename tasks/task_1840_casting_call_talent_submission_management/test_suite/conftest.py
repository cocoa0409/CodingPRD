"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def associate_headers():
    return TEST_USERS["associate_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]
