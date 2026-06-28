"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and manages server
lifecycle (restarting the server via start.sh before each test). This file only
wires test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def notary_headers():
    return TEST_USERS["notary_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def server_headers():
    return TEST_USERS["server_headers"]
