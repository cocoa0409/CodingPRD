"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def livestock_keeper_headers():
    return TEST_USERS["livestock_keeper_headers"]


@pytest.fixture
def clinic_vet_headers():
    return TEST_USERS["clinic_vet_headers"]


@pytest.fixture
def store_clerk_headers():
    return TEST_USERS["store_clerk_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
