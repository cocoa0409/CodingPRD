"""Pytest fixtures exposing the Broadband Grant Challenge test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def program_admin_2_headers():
    return TEST_USERS["program_admin_2_headers"]


@pytest.fixture
def eligibility_analyst_headers():
    return TEST_USERS["eligibility_analyst_headers"]


@pytest.fixture
def eligibility_analyst_2_headers():
    return TEST_USERS["eligibility_analyst_2_headers"]


@pytest.fixture
def capability_reviewer_headers():
    return TEST_USERS["capability_reviewer_headers"]


@pytest.fixture
def capability_reviewer_2_headers():
    return TEST_USERS["capability_reviewer_2_headers"]


@pytest.fixture
def scoring_officer_headers():
    return TEST_USERS["scoring_officer_headers"]


@pytest.fixture
def scoring_officer_2_headers():
    return TEST_USERS["scoring_officer_2_headers"]


@pytest.fixture
def environmental_reviewer_headers():
    return TEST_USERS["environmental_reviewer_headers"]


@pytest.fixture
def audit_officer_headers():
    return TEST_USERS["audit_officer_headers"]


@pytest.fixture
def audit_officer_2_headers():
    return TEST_USERS["audit_officer_2_headers"]


@pytest.fixture
def challenger_headers():
    return TEST_USERS["challenger_headers"]


@pytest.fixture
def challenger_other_headers():
    return TEST_USERS["challenger_other_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def provider_other_headers():
    return TEST_USERS["provider_other_headers"]


@pytest.fixture
def provider_stranger_headers():
    return TEST_USERS["provider_stranger_headers"]
