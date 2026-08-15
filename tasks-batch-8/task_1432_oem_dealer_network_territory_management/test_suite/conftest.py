"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def oem_admin_headers():
    return TEST_USERS["oem_admin_headers"]


@pytest.fixture
def sales_ops_headers():
    return TEST_USERS["sales_ops_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def dealer_user_headers():
    return TEST_USERS["dealer_user_headers"]
