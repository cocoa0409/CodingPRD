"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures just hand the
shared client and role headers to tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def field_tech_headers():
    return TEST_USERS["field_tech_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
