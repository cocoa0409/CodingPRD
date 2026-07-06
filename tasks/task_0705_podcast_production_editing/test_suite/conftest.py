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
def ad_ops_headers():
    return TEST_USERS["ad_ops_headers"]


@pytest.fixture
def show_owner_headers():
    return TEST_USERS["show_owner_headers"]


@pytest.fixture
def producer_eng_headers():
    return TEST_USERS["producer_eng_headers"]
