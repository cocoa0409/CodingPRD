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
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def resort_ops_headers():
    return TEST_USERS["resort_ops_headers"]


@pytest.fixture
def refund_admin_headers():
    return TEST_USERS["refund_admin_headers"]
