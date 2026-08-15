"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["governance_admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def exec_director_headers():
    return TEST_USERS["executive_director_headers"]
