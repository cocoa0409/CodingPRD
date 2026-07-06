"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_member_headers, make_organizer_headers, make_admin_headers,
    unauthenticated_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def missing_headers():
    """No X-User-Role / X-User-ID — used to trigger ERR_UNAUTHENTICATED."""
    return unauthenticated_headers()


@pytest.fixture
def as_member():
    """Builder for entity-owned Member headers (X-User-ID = the member's id)."""
    return make_member_headers


@pytest.fixture
def as_organizer():
    """Builder for entity-owned ProjectOrganizer headers."""
    return make_organizer_headers


@pytest.fixture
def as_admin():
    """Builder for opaque PlatformAdmin headers."""
    return make_admin_headers
