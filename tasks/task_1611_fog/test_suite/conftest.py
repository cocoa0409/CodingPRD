"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def fse_contact_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["fse_contact_headers"]


@pytest.fixture
def hauler_admin_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["hauler_admin_headers"]
