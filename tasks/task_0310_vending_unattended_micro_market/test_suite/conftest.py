"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable without sys.path
hacks, and manages the server lifecycle (restart before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def field_ops_headers():
    return TEST_USERS["field_ops_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def route_driver_headers():
    return TEST_USERS["route_driver_headers"]


@pytest.fixture
def host_manager_headers():
    return TEST_USERS["host_manager_headers"]
