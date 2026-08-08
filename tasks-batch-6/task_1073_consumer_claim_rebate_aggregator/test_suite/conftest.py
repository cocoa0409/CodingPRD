"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle and PYTHONPATH; these
fixtures merely surface the shared client and role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def claim_reviewer_headers():
    return TEST_USERS["claim_reviewer_headers"]


@pytest.fixture
def fraud_analyst_1_headers():
    return TEST_USERS["fraud_analyst_1_headers"]


@pytest.fixture
def fraud_analyst_2_headers():
    return TEST_USERS["fraud_analyst_2_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]
