"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ehs_manager_headers():
    return TEST_USERS["ehs_manager_headers"]


@pytest.fixture
def waste_coordinator_headers():
    return TEST_USERS["waste_coordinator_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def transporter_agent_headers():
    return TEST_USERS["transporter_agent_headers"]


@pytest.fixture
def tsdf_agent_headers():
    return TEST_USERS["tsdf_agent_headers"]
