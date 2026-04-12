"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS

@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client

@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]

@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]

@pytest.fixture
def seller2_headers():
    return TEST_USERS["seller2_headers"]

@pytest.fixture
def customer2_headers():
    return TEST_USERS["customer2_headers"]
