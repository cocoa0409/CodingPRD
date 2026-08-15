"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def wholesale_admin_headers():
    return TEST_USERS["wholesale_admin_headers"]


@pytest.fixture
def operator_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["operator_manager_headers"]


@pytest.fixture
def route_planner_headers():
    return TEST_USERS["route_planner_headers"]


@pytest.fixture
def warehouse_ops_headers():
    return TEST_USERS["warehouse_ops_headers"]


@pytest.fixture
def credit_adjuster_headers():
    return TEST_USERS["credit_adjuster_headers"]


@pytest.fixture
def telemetry_gateway_headers():
    return TEST_USERS["telemetry_gateway_headers"]
