"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, sets API_BASE_URL, and
manages server lifecycle (restart before every test). These fixtures just wire
the client and role headers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sales_associate_headers():
    return TEST_USERS["sales_associate_headers"]


@pytest.fixture
def fitting_specialist_headers():
    return TEST_USERS["fitting_specialist_headers"]


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
