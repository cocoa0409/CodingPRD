"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable directly. Server
lifecycle is the runner's job; these fixtures just wire up the client and headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer constant — for non-ownership Customer tests only."""
    return TEST_USERS["customer_headers"]
