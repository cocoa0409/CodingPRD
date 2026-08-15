"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def compliance_admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def surveillance_analyst_headers():
    return TEST_USERS["surveillance_analyst_headers"]


@pytest.fixture
def filing_officer_headers():
    return TEST_USERS["filing_officer_headers"]
