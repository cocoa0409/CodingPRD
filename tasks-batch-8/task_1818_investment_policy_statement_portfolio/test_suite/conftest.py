"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def client_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["client_headers"]
