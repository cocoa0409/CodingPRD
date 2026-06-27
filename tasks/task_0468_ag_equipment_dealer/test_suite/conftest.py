"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle and PYTHONPATH; these
fixtures only wire up the shared API client and per-role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dealer_admin_headers():
    return TEST_USERS["dealer_admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def service_advisor_headers():
    return TEST_USERS["service_advisor_headers"]


@pytest.fixture
def parts_clerk_headers():
    return TEST_USERS["parts_clerk_headers"]


@pytest.fixture
def auction_clerk_headers():
    return TEST_USERS["auction_clerk_headers"]
