"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def conference_admin_headers():
    return TEST_USERS["conference_admin_headers"]


@pytest.fixture
def program_chair_headers():
    return TEST_USERS["program_chair_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def author_headers():
    return TEST_USERS["author_headers"]


@pytest.fixture
def press_officer_headers():
    return TEST_USERS["press_officer_headers"]
