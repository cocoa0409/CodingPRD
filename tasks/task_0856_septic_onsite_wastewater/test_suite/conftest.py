"""Pytest fixtures exposing the register's test infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def other_applicant_headers():
    return TEST_USERS["other_applicant_headers"]


@pytest.fixture
def design_professional_headers():
    return TEST_USERS["design_professional_headers"]


@pytest.fixture
def other_design_professional_headers():
    return TEST_USERS["other_design_professional_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]


@pytest.fixture
def pumper_headers():
    return TEST_USERS["pumper_headers"]


@pytest.fixture
def ehs_reviewer_headers():
    return TEST_USERS["ehs_reviewer_headers"]


@pytest.fixture
def ehs_field_headers():
    return TEST_USERS["ehs_field_headers"]


@pytest.fixture
def health_officer_headers():
    return TEST_USERS["health_officer_headers"]


@pytest.fixture
def records_clerk_headers():
    return TEST_USERS["records_clerk_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
