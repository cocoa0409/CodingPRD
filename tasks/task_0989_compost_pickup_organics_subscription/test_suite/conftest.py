"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed externally; tests assume the API is reachable
at API_BASE_URL and starts from an empty database with the logical clock at
2026-05-01T00:00:00Z (PRD §2.4).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def driver2_headers():
    return TEST_USERS["driver2_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def ops2_headers():
    return TEST_USERS["ops2_headers"]
