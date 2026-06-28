"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def aggregator_gateway_headers():
    return TEST_USERS["aggregator_gateway_headers"]


@pytest.fixture
def stall_operator_headers():
    return TEST_USERS["stall_operator_headers"]


@pytest.fixture
def brand_owner_headers():
    return TEST_USERS["brand_owner_headers"]
