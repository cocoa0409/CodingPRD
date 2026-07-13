"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ANONYMOUS, NO_AUTH, PLATFORM, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_headers() -> dict:
    """PlatformAdmin — opaque identity, not scoped to any tenant (PRD §2.1)."""
    return PLATFORM


@pytest.fixture
def anon_headers() -> dict:
    """Anonymous — X-User-Role only, no X-User-ID (PRD §2.1)."""
    return ANONYMOUS


@pytest.fixture
def unauthenticated_headers() -> dict:
    """No X-User-Role header at all (PRD §2.1)."""
    return NO_AUTH
