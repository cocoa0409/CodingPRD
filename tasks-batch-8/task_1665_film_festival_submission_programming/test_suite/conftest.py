"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL and starts empty for every test.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def chair_headers():
    return TEST_USERS["chair_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def travel_headers():
    return TEST_USERS["travel_headers"]


@pytest.fixture
def awards_headers():
    return TEST_USERS["awards_headers"]
