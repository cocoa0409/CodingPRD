"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restarts before every test) and PYTHONPATH,
so test_helpers is importable without sys.path hacks and each test starts against
a fresh empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def studio_manager_headers():
    return TEST_USERS["studio_manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
