"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def catalog_manager_headers():
    return TEST_USERS["catalog_manager_headers"]


@pytest.fixture
def warehouse_ops_headers():
    return TEST_USERS["warehouse_ops_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]
