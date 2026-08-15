"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def warehouse_manager_headers():
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def rebate_clerk_headers():
    return TEST_USERS["rebate_clerk_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
