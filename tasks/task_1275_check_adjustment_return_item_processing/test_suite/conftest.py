"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operations_admin_headers():
    return TEST_USERS["operations_admin_headers"]


@pytest.fixture
def item_processor_headers():
    return TEST_USERS["item_processor_headers"]


@pytest.fixture
def adjustment_analyst_headers():
    return TEST_USERS["adjustment_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]
