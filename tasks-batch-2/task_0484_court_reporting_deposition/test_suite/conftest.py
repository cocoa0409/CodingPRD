"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (it restarts the server with an empty DB before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def schedule_coordinator_headers():
    return TEST_USERS["schedule_coordinator_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def reporter_headers():
    return TEST_USERS["reporter_headers"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]
