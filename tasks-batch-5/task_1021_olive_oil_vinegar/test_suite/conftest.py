"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-before-each-test) is owned by prd-bench-local-runner.
These fixtures only hand tests the shared API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["shop_staff_headers"]


@pytest.fixture
def inventory_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["wholesale_approver_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
