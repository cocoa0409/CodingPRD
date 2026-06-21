"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restarting it before every test). These fixtures just wire
up the API client and the role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def location_agent_headers():
    return TEST_USERS["location_agent_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
