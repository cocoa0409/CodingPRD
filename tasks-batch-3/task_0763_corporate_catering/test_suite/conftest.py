"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; conftest only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def site_admin_headers():
    return TEST_USERS["site_admin_headers"]


@pytest.fixture
def cafeteria_manager_headers():
    return TEST_USERS["cafeteria_manager_headers"]


@pytest.fixture
def catering_coordinator_headers():
    return TEST_USERS["catering_coordinator_headers"]


@pytest.fixture
def catering_approver_headers():
    return TEST_USERS["catering_approver_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def diner_headers():
    return TEST_USERS["diner_headers"]
