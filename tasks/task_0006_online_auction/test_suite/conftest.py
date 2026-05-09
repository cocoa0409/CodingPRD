"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_ops_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def seller_fallback_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def bidder_fallback_headers():
    return TEST_USERS["bidder_headers"]
