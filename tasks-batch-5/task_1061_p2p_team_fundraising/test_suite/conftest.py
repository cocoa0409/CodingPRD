"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def reviewer_one_headers():
    return TEST_USERS["finance_reviewer_headers"]


@pytest.fixture
def reviewer_two_headers():
    return TEST_USERS["finance_reviewer_two_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def campaign_manager_headers():
    return TEST_USERS["campaign_manager_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def donor_headers():
    return TEST_USERS["donor_headers"]
