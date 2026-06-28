"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and the server lifecycle (the server is killed
and relaunched before every individual test, so every test starts against an
empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def homeowner_headers():
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def sales_consultant_headers():
    return TEST_USERS["sales_consultant_headers"]


@pytest.fixture
def operations_coordinator_headers():
    return TEST_USERS["operations_coordinator_headers"]


@pytest.fixture
def service_tech_headers():
    return TEST_USERS["service_tech_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
