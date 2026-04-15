"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_2():
    return TEST_USERS["admin_headers_2"]


@pytest.fixture
def restaurant_headers():
    return TEST_USERS["restaurant_headers"]


@pytest.fixture
def restaurant_headers_2():
    return TEST_USERS["restaurant_headers_2"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def customer_headers_2():
    return TEST_USERS["customer_headers_2"]


@pytest.fixture
def rider_headers():
    return TEST_USERS["rider_headers"]


@pytest.fixture
def rider_headers_2():
    return TEST_USERS["rider_headers_2"]


@pytest.fixture
def cs_headers():
    return TEST_USERS["cs_headers"]


@pytest.fixture
def cs_headers_2():
    return TEST_USERS["cs_headers_2"]
