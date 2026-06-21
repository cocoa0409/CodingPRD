"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests assume the server is
already running and reachable at API_BASE_URL.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def caregiver_headers():
    return TEST_USERS["caregiver_headers"]


@pytest.fixture
def bcba_headers():
    return TEST_USERS["bcba_headers"]


@pytest.fixture
def rbt_headers():
    return TEST_USERS["rbt_headers"]
