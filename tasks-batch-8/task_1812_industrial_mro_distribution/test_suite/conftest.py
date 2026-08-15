"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]
