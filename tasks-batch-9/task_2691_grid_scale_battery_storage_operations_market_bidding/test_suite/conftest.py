"""Pytest fixtures exposing the test_helpers infrastructure to every test file."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.fixtures import *  # noqa: F401,F403  (composite setup fixtures)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def site_controller_headers():
    """Shared fallback identity — never use it for an ownership-gated call."""
    return TEST_USERS["site_controller_headers"]
