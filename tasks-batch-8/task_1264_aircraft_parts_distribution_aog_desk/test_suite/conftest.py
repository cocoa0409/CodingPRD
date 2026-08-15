"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def aog_desk_agent_headers():
    return TEST_USERS["aog_desk_agent_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def warranty_adjuster_headers():
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def warranty_approver_headers():
    return TEST_USERS["warranty_approver_headers"]


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]
