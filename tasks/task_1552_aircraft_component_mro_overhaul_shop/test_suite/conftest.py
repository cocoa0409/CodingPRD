"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    CSR,
    INSPECTOR,
    PARTS_BUYER,
    SHOP_MANAGER,
    TECHNICIAN,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def csr_headers():
    return TEST_USERS["csr_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def parts_buyer_headers():
    return TEST_USERS["parts_buyer_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer headers. Ownership-gated calls must instead use
    test_helpers.make_customer_headers(customer['id'])."""
    return TEST_USERS["customer_headers"]
