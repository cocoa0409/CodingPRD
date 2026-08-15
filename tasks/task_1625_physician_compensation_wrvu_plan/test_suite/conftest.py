"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_2_headers():
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def committee_9_headers():
    return TEST_USERS["committee_9_headers"]


@pytest.fixture
def physician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["physician_headers"]
