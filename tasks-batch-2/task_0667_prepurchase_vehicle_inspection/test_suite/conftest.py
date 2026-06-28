"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]
