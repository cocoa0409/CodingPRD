"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def meter_attester_headers():
    return TEST_USERS["meter_attester_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def generator_operator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["generator_operator_headers"]


@pytest.fixture
def broker_trader_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["broker_trader_headers"]
