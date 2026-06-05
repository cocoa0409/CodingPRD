"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests assume the server is
already running and reachable at API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def background_screener_headers():
    return TEST_USERS["background_screener_headers"]


@pytest.fixture
def match_specialist_headers():
    return TEST_USERS["match_specialist_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]
