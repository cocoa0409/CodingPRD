"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def librarian_headers():
    return TEST_USERS["librarian_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def senior_reviewer_headers():
    return TEST_USERS["senior_reviewer_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def provider_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["provider_headers"]
