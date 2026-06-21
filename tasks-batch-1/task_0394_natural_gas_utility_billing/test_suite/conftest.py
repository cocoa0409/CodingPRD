"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and starts/stops the server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def field_tech_headers():
    return TEST_USERS["field_tech_headers"]


@pytest.fixture
def account_headers():
    return TEST_USERS["account_headers"]
