"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def athletics_admin_headers():
    return TEST_USERS["athletics_admin_headers"]


@pytest.fixture
def field_supervisor_headers():
    return TEST_USERS["field_supervisor_headers"]


@pytest.fixture
def org_coordinator_headers():
    return TEST_USERS["org_coordinator_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]
