"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the server
lifecycle (the API server is re-launched before every individual test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_dispatcher_headers():
    return TEST_USERS["ops_dispatcher_headers"]


@pytest.fixture
def fuel_tech_headers():
    return TEST_USERS["fuel_tech_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def line_manager_headers():
    return TEST_USERS["line_manager_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]
