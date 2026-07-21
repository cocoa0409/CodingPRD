"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and injects
API_BASE_URL; it also restarts the server (empty DB, clock reset) before
every test.
"""
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
def merch_headers():
    return TEST_USERS["merch_headers"]


@pytest.fixture
def associate_headers():
    return TEST_USERS["associate_headers"]


@pytest.fixture
def delivery_headers():
    return TEST_USERS["delivery_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
