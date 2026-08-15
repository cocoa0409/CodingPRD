"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL with a fresh database per test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def supervisor_headers() -> dict:
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def dpo_headers() -> dict:
    return TEST_USERS["dpo_headers"]


@pytest.fixture
def analyst_headers() -> dict:
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
