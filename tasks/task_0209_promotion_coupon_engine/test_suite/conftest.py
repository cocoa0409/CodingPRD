"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def merchant_admin_headers():
    return TEST_USERS["merchant_admin_headers"]


@pytest.fixture
def shopper_headers():
    return TEST_USERS["shopper_headers"]


@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]
