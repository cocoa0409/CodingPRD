"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer2_headers():
    return TEST_USERS["officer2_headers"]


@pytest.fixture
def resident_headers():
    """Fallback Resident headers whose X-User-ID does NOT match any live entity —
    use ONLY in tests that expect 401 for an unknown Resident id."""
    return TEST_USERS["resident_headers"]


@pytest.fixture
def moderator_headers():
    """Fallback Moderator headers (unknown Resident id). Same caveat."""
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def business_owner_headers():
    """Fallback BusinessOwner headers (unknown Business id). Same caveat."""
    return TEST_USERS["business_owner_headers"]
