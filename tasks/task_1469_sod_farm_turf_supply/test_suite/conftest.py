"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def harvest_supervisor_headers():
    return TEST_USERS["harvest_supervisor_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
