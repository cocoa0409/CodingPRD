"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by the runner; tests assume the API is
reachable at API_BASE_URL and the database starts empty for every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def intake_operator_headers():
    return TEST_USERS["intake_operator_headers"]


@pytest.fixture
def destruction_technician_headers():
    return TEST_USERS["destruction_technician_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]
