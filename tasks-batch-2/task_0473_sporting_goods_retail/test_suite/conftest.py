"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires
test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def store_associate_headers():
    return TEST_USERS["store_associate_headers"]


@pytest.fixture
def service_tech_headers():
    return TEST_USERS["service_tech_headers"]


@pytest.fixture
def price_admin_headers():
    return TEST_USERS["price_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
