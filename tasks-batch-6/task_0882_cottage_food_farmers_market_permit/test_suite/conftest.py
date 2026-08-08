"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def market_manager_headers():
    return TEST_USERS["market_manager_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
