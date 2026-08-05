"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (restarting before every test). Tests never start/stop the server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["permit_supervisor_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["parking_clerk_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def officer2_headers():
    return TEST_USERS["enforcement_officer_2_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
