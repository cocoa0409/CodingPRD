"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH, and API_BASE_URL are managed by the runner.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def race_director_headers():
    return TEST_USERS["race_director_headers"]


@pytest.fixture
def packet_staff_headers():
    return TEST_USERS["packet_staff_headers"]


@pytest.fixture
def timing_official_headers():
    return TEST_USERS["timing_official_headers"]
