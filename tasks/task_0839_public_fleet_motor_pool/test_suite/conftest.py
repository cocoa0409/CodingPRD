"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def motor_pool_clerk_headers():
    return TEST_USERS["motor_pool_clerk_headers"]


@pytest.fixture
def shop_tech_headers():
    return TEST_USERS["shop_tech_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def department_user_headers():
    return TEST_USERS["department_user_headers"]
