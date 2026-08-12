"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_quote_headers"]


@pytest.fixture
def quoting_manager_headers():
    return TEST_USERS["case_manager_quote_headers"]


@pytest.fixture
def reviewing_manager_headers():
    return TEST_USERS["case_manager_review_headers"]


@pytest.fixture
def submitting_manager_headers():
    return TEST_USERS["case_manager_submit_headers"]


@pytest.fixture
def splitting_manager_headers():
    return TEST_USERS["case_manager_split_headers"]


@pytest.fixture
def courier_ops_headers():
    return TEST_USERS["courier_ops_headers"]


@pytest.fixture
def agency_liaison_headers():
    return TEST_USERS["agency_liaison_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def traveler_headers():
    return TEST_USERS["traveler_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
