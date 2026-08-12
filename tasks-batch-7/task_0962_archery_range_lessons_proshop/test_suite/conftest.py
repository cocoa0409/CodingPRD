"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests assume the server
is already running and reachable at API_BASE_URL.
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
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def range_officer_headers():
    return TEST_USERS["range_officer_headers"]


@pytest.fixture
def shop_clerk_headers():
    return TEST_USERS["shop_clerk_headers"]


@pytest.fixture
def league_director_headers():
    return TEST_USERS["league_director_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
