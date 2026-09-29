"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def fiscal_officer_headers():
    return TEST_USERS["fiscal_officer_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def drafter_headers():
    return TEST_USERS["drafter_headers"]


@pytest.fixture
def review_counsel_headers():
    return TEST_USERS["review_counsel_headers"]


@pytest.fixture
def agency_analyst_headers():
    return TEST_USERS["agency_analyst_headers"]
