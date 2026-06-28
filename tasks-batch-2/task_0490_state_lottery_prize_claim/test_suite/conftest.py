"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def licensing_admin_headers():
    return TEST_USERS["licensing_admin_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def claims_clerk_headers():
    return TEST_USERS["claims_clerk_headers"]


@pytest.fixture
def lottery_officer_headers():
    return TEST_USERS["lottery_officer_headers"]
