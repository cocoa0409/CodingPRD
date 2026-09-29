"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_reviewer_headers():
    return TEST_USERS["coordinator_reviewer_headers"]


@pytest.fixture
def coordinator_third_headers():
    return TEST_USERS["coordinator_third_headers"]


@pytest.fixture
def coordinator_fourth_headers():
    return TEST_USERS["coordinator_fourth_headers"]


@pytest.fixture
def quality_auditor_headers():
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def quality_auditor_second_headers():
    return TEST_USERS["quality_auditor_second_headers"]


@pytest.fixture
def cleaner_headers():
    return TEST_USERS["cleaner_headers"]


@pytest.fixture
def property_owner_headers():
    return TEST_USERS["property_owner_headers"]
