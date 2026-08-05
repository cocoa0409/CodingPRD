"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def health_officer_headers():
    return TEST_USERS["health_officer_headers"]


@pytest.fixture
def health_officer_2_headers():
    return TEST_USERS["health_officer_2_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_2_headers():
    return TEST_USERS["inspector_2_headers"]


@pytest.fixture
def plan_reviewer_headers():
    return TEST_USERS["plan_reviewer_headers"]


@pytest.fixture
def records_clerk_headers():
    return TEST_USERS["records_clerk_headers"]


@pytest.fixture
def public_user_headers():
    return TEST_USERS["public_user_headers"]
