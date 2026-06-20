"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the server
lifecycle (restarts via start.sh before every test). Tests assume the server is
already running and reachable at API_BASE_URL.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def grid_operator_headers():
    return TEST_USERS["grid_operator_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]
