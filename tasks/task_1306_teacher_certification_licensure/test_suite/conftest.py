"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def credential_evaluator_headers():
    return TEST_USERS["credential_evaluator_headers"]


@pytest.fixture
def background_investigator_headers():
    return TEST_USERS["background_investigator_headers"]


@pytest.fixture
def legal_officer_headers():
    return TEST_USERS["legal_officer_headers"]


@pytest.fixture
def program_approval_officer_headers():
    return TEST_USERS["program_approval_officer_headers"]


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]
