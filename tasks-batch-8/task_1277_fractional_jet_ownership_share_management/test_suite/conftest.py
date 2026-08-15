"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def fleet_ops_headers():
    return TEST_USERS["fleet_ops_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
