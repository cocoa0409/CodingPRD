"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["security_admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def resident_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["resident_headers"]


@pytest.fixture
def vendor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["vendor_headers"]
