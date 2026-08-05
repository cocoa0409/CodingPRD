"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["attendance_clerk_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def court_officer_headers():
    return TEST_USERS["court_officer_headers"]
