"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def court_admin_headers():
    return TEST_USERS["court_admin_headers"]


@pytest.fixture
def court_clerk_headers():
    return TEST_USERS["court_clerk_headers"]


@pytest.fixture
def paralegal_headers():
    return TEST_USERS["paralegal_headers"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]
