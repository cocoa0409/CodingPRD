"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dei_admin_headers():
    return TEST_USERS["dei_admin_headers"]


@pytest.fixture
def group_leader_headers():
    return TEST_USERS["group_leader_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]
