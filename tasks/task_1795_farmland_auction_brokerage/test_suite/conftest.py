"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin is an opaque role — the shared constant is canonical."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def seller_headers():
    """Shared Seller headers — only for calls that are not ownership-gated."""
    return TEST_USERS["seller_headers"]


@pytest.fixture
def agent_headers():
    """Shared BrokerAgent headers — only for calls that are not ownership-gated."""
    return TEST_USERS["agent_headers"]


@pytest.fixture
def buyer_headers():
    """Shared Buyer headers — only for calls that are not ownership-gated."""
    return TEST_USERS["buyer_headers"]
