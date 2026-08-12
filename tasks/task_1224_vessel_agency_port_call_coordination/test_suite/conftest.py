"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def agency_ops_headers():
    return TEST_USERS["agency_ops_headers"]


@pytest.fixture
def agency_finance_headers():
    return TEST_USERS["agency_finance_headers"]


@pytest.fixture
def port_authority_headers():
    return TEST_USERS["port_authority_headers"]


@pytest.fixture
def principal_rep_headers():
    return TEST_USERS["principal_rep_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]


@pytest.fixture
def crewing_agent_headers():
    return TEST_USERS["crewing_agent_headers"]


@pytest.fixture
def husbandry_officer_headers():
    return TEST_USERS["husbandry_officer_headers"]
