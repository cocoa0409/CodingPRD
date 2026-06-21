"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def toll_operator_headers():
    return TEST_USERS["toll_operator_headers"]


@pytest.fixture
def interop_clerk_headers():
    return TEST_USERS["interop_clerk_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
