"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["shop_staff_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
