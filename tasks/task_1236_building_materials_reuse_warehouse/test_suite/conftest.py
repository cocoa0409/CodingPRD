"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_staff_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["warehouse_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["crew_coordinator_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]
