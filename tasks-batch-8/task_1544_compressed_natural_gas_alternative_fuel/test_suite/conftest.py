"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_operator_headers():
    return TEST_USERS["network_operator_headers"]


@pytest.fixture
def station_manager_headers():
    return TEST_USERS["station_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def fleet_account_manager_headers():
    return TEST_USERS["fleet_account_manager_headers"]


@pytest.fixture
def fleet_driver_headers():
    return TEST_USERS["fleet_driver_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
