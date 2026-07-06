"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only surface the shared API client and
role headers. Every test builds its own data from scratch.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def install_coordinator_headers():
    return TEST_USERS["install_coordinator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
