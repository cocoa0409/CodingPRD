"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable, and it manages
the server lifecycle (restart before every test). These fixtures only wire the
client and role headers into pytest.
"""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_facility_operator_headers, make_compliance_officer_headers,
    make_customer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["facility_operator_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
