"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project root
to PYTHONPATH before invoking pytest, so test_helpers imports cleanly.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def portability_coordinator_headers():
    return TEST_USERS["portability_coordinator_headers"]


@pytest.fixture
def landlord_headers_fallback():
    """Fallback Landlord headers; safe only for tests where the rejection is a
    forbidden-role check (the literal X-User-ID need not match a real id)."""
    return TEST_USERS["landlord_headers"]
