"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers() -> dict:
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def account_manager_headers() -> dict:
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def ehs_officer_headers() -> dict:
    return TEST_USERS["ehs_officer_headers"]
