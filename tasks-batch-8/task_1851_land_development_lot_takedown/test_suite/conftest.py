"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def developer_operator_headers():
    return TEST_USERS["developer_operator_headers"]


@pytest.fixture
def builder_rep_headers():
    return TEST_USERS["builder_rep_headers"]


@pytest.fixture
def lender_officer_headers():
    return TEST_USERS["lender_officer_headers"]


@pytest.fixture
def municipal_clerk_headers():
    return TEST_USERS["municipal_clerk_headers"]


@pytest.fixture
def hoa_manager_headers():
    return TEST_USERS["hoa_manager_headers"]
