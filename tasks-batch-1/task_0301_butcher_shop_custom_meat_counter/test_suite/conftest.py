"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def counter_clerk_headers():
    return TEST_USERS["counter_clerk_headers"]


@pytest.fixture
def butcher_headers():
    return TEST_USERS["butcher_headers"]


@pytest.fixture
def shift_manager_headers():
    return TEST_USERS["shift_manager_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]
