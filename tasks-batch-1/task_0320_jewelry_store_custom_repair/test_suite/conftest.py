"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) and PYTHONPATH are owned by
prd-bench-local-runner; this file only wires test_helpers into pytest fixtures.
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
def goldsmith_headers():
    return TEST_USERS["goldsmith_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
