"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (a fresh empty-DB server before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def putaway_operator_headers():
    return TEST_USERS["putaway_operator_headers"]


@pytest.fixture
def picker_headers():
    return TEST_USERS["picker_headers"]


@pytest.fixture
def wave_planner_headers():
    return TEST_USERS["wave_planner_headers"]


@pytest.fixture
def inventory_controller_headers():
    return TEST_USERS["inventory_controller_headers"]
