"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def rental_coordinator_headers():
    return TEST_USERS["rental_coordinator_headers"]


@pytest.fixture
def service_dispatcher_headers():
    return TEST_USERS["service_dispatcher_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def training_registrar_headers():
    return TEST_USERS["training_registrar_headers"]


@pytest.fixture
def lease_manager_headers():
    return TEST_USERS["lease_manager_headers"]
