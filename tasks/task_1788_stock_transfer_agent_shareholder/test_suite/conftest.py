"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agent_admin_headers():
    return TEST_USERS["agent_admin_headers"]


@pytest.fixture
def shareholder_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["shareholder_headers"]


@pytest.fixture
def transfer_examiner_headers():
    return TEST_USERS["transfer_examiner_headers"]


@pytest.fixture
def transfer_supervisor_headers():
    return TEST_USERS["transfer_supervisor_headers"]


@pytest.fixture
def issuer_officer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["issuer_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def service_agent_headers():
    return TEST_USERS["service_agent_headers"]
