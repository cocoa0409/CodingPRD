"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def gate_controller_headers():
    return TEST_USERS["gate_controller_headers"]


@pytest.fixture
def ramp_agent_headers():
    return TEST_USERS["ramp_agent_headers"]


@pytest.fixture
def slot_coordinator_headers():
    return TEST_USERS["slot_coordinator_headers"]
