"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before each test) and PYTHONPATH;
these fixtures simply expose the shared API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["terminal_admin_headers"]


@pytest.fixture
def berth_planner_headers():
    return TEST_USERS["berth_planner_headers"]


@pytest.fixture
def yard_planner_headers():
    return TEST_USERS["yard_planner_headers"]


@pytest.fixture
def gate_operator_headers():
    return TEST_USERS["gate_operator_headers"]


@pytest.fixture
def customs_officer_headers():
    return TEST_USERS["customs_officer_headers"]


@pytest.fixture
def reefer_technician_headers():
    return TEST_USERS["reefer_technician_headers"]
