"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def change_admin_headers():
    return TEST_USERS["change_admin_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def supplier_manager_headers():
    return TEST_USERS["supplier_manager_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]
