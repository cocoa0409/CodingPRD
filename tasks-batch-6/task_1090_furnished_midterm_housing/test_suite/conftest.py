"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before every test) and PYTHONPATH,
so test_helpers is importable directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
