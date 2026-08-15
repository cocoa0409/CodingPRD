"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def volunteer_headers():
    """Fallback Volunteer headers — never for ownership-gated calls."""
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def member_headers():
    """Fallback Member headers — never for ownership-gated calls."""
    return TEST_USERS["member_headers"]
