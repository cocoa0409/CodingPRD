"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, create_test_users


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def users():
    """Fresh set of SystemUser-backed role headers for each test (the server
    restarts before every test, so users are created against an empty DB)."""
    return create_test_users()


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
