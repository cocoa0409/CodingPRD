"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["pm_headers"]


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def anonymous_headers():
    """The Anonymous placeholder: both auth headers are omitted entirely."""
    return TEST_USERS["anonymous_headers"]
