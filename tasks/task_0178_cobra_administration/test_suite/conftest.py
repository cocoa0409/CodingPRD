"""Pytest fixtures exposing test_helpers infrastructure for the COBRA
Administration suite. The runner manages server lifecycle and PYTHONPATH; these
tests assume the server is already running at API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["plan_administrator_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["plan_sponsor_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def beneficiary_headers():
    return TEST_USERS["qualified_beneficiary_headers"]
