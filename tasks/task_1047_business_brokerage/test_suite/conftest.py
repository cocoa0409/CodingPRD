"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/health) is managed by prd-bench-local-runner;
these fixtures only expose the API client and pre-built role headers.
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
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def lender_headers():
    return TEST_USERS["lender_headers"]


@pytest.fixture
def escrow_agent_headers():
    return TEST_USERS["escrow_agent_headers"]
