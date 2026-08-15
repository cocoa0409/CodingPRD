"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def carrier_ops_headers():
    return TEST_USERS["carrier_ops_headers"]


@pytest.fixture
def agency_dispatcher_headers():
    return TEST_USERS["agency_dispatcher_headers"]


@pytest.fixture
def pilot_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["pilot_headers"]


@pytest.fixture
def carrier_finance_headers():
    return TEST_USERS["carrier_finance_headers"]


@pytest.fixture
def agency_finance_headers():
    return TEST_USERS["agency_finance_headers"]


@pytest.fixture
def carding_inspector_headers():
    return TEST_USERS["carding_inspector_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
