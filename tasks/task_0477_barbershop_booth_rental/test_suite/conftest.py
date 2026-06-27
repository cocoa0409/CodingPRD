"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def owner_headers():
    return TEST_USERS["shop_owner_headers"]


@pytest.fixture
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def barber_headers():
    return TEST_USERS["barber_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
