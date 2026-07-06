"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers.test_users import make_customer_headers, make_delivery_driver_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def shop_staff_headers():
    return TEST_USERS["shop_staff_headers"]


@pytest.fixture
def horticulturist_headers():
    return TEST_USERS["horticulturist_headers"]


@pytest.fixture
def delivery_driver_headers():
    return TEST_USERS["delivery_driver_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def build_customer_headers():
    """Builder fixture — returns the maker so tests can thread the actual Customer.id."""
    return make_customer_headers


@pytest.fixture
def build_driver_headers():
    """Builder fixture — returns the maker so tests can thread the actual DeliveryDriver.id."""
    return make_delivery_driver_headers
