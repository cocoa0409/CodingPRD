"""Pytest fixtures exposing test_helpers infrastructure."""
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
def publisher_headers():
    return TEST_USERS["publisher_headers"]


@pytest.fixture
def advertiser_headers():
    return TEST_USERS["advertiser_headers"]


@pytest.fixture
def listener_headers():
    return TEST_USERS["listener_headers"]
