"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and supplies a running
server at API_BASE_URL. These fixtures never start/stop the server; the harness
restarts it before every individual test, so each test starts from an empty DB.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def bonds_agent_headers():
    return TEST_USERS["bonds_agent_headers"]


@pytest.fixture
def court_headers():
    return TEST_USERS["court_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def recovery_agent_headers():
    return TEST_USERS["recovery_agent_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
