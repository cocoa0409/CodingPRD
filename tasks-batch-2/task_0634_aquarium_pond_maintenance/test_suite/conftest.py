"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def field_tech_headers():
    return TEST_USERS["field_tech_headers"]


@pytest.fixture
def customer_owner_headers():
    return TEST_USERS["customer_owner_headers"]
