"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project root
to PYTHONPATH before invoking pytest, so ``test_helpers`` imports cleanly and the
server is already running and reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers.test_users import ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["community_admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def resident_headers_fallback():
    """Resident headers whose X-User-ID does not match any real resident; safe
    only for forbidden-role / not-found rejections that never reach an ownership
    comparison."""
    return TEST_USERS["resident_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
