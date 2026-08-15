"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; these tests
assume the server is already running and freshly restarted (empty database,
logical clock at the PRD 2.5 startup value) before every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def licensing_coordinator_headers():
    return TEST_USERS["licensing_coordinator_headers"]


@pytest.fixture
def compliance_officer_a_headers():
    return TEST_USERS["compliance_officer_a_headers"]


@pytest.fixture
def compliance_officer_b_headers():
    return TEST_USERS["compliance_officer_b_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def carrier_admin_headers():
    return TEST_USERS["carrier_admin_headers"]
