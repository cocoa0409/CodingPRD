"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/restart/health) is owned by prd-bench-local-runner;
these fixtures only surface the shared API client and role headers.
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
def facility_operator_headers():
    return TEST_USERS["facility_operator_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]
