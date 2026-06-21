"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires
test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_customer_headers, make_lot_operator_headers, make_facility_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def lot_operator_headers():
    return TEST_USERS["lot_operator_headers"]


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def make_customer():
    return make_customer_headers


@pytest.fixture
def make_lot_operator():
    return make_lot_operator_headers


@pytest.fixture
def make_facility_admin():
    return make_facility_admin_headers
