"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_approver_headers():
    return TEST_USERS["claims_approver_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]
