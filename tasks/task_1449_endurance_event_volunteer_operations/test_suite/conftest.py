"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and API_BASE_URL injection; these tests
assume the server is already running and reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def captain_headers():
    return TEST_USERS["captain_headers"]


@pytest.fixture
def group_leader_headers():
    return TEST_USERS["group_leader_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]
