"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and PYTHONPATH; the server process is
re-launched before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def race_director_headers():
    return TEST_USERS["race_director_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]


@pytest.fixture
def referee_headers():
    return TEST_USERS["referee_headers"]


@pytest.fixture
def timer_headers():
    return TEST_USERS["timer_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def athlete_headers():
    return TEST_USERS["athlete_headers"]
