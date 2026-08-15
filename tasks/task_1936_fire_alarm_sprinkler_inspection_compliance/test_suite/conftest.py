"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def fire_marshal_headers():
    return TEST_USERS["fire_marshal_headers"]


@pytest.fixture
def contractor_admin_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def technician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["technician_headers"]
