"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def csr_headers():
    return TEST_USERS["csr_headers"]


@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def fieldcrew_headers():
    return TEST_USERS["fieldcrew_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
