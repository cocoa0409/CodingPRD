"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def claims_analyst_headers():
    return TEST_USERS["claims_analyst_headers"]


@pytest.fixture
def tpa_agent_headers():
    return TEST_USERS["tpa_agent_headers"]


@pytest.fixture
def agency_liaison_headers():
    return TEST_USERS["agency_liaison_headers"]


@pytest.fixture
def charge_auditor_headers():
    return TEST_USERS["charge_auditor_headers"]


@pytest.fixture
def rating_analyst_headers():
    return TEST_USERS["rating_analyst_headers"]


@pytest.fixture
def tpa_manager_headers():
    return TEST_USERS["tpa_manager_headers"]
