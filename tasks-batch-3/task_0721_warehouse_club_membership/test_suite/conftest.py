"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def club_admin_headers():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def register_clerk_headers():
    return TEST_USERS["register_clerk_headers"]


@pytest.fixture
def service_desk_headers():
    return TEST_USERS["service_desk_headers"]
