"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and sets API_BASE_URL
before the pytest subprocess. The server is already running and reachable; these
fixtures never start, stop, or health-check it.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def schedule_manager_headers():
    return TEST_USERS["schedule_manager_headers"]


@pytest.fixture
def fare_analyst_headers():
    return TEST_USERS["fare_analyst_headers"]


@pytest.fixture
def gate_agent_headers():
    return TEST_USERS["gate_agent_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def passenger_headers():
    return TEST_USERS["passenger_headers"]
