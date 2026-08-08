"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]


@pytest.fixture
def site_coordinator_headers():
    return TEST_USERS["site_coordinator_headers"]


@pytest.fixture
def field_dentist_headers():
    return TEST_USERS["field_dentist_headers"]


@pytest.fixture
def field_hygienist_headers():
    return TEST_USERS["field_hygienist_headers"]


@pytest.fixture
def dental_assistant_headers():
    return TEST_USERS["dental_assistant_headers"]
