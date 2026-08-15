"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def hiring_manager_headers():
    return TEST_USERS["hiring_manager_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def vendor_agent_headers():
    return TEST_USERS["vendor_agent_headers"]
