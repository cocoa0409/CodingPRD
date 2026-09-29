"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def grants_officer_headers():
    return TEST_USERS["grants_officer_headers"]


@pytest.fixture
def second_grants_officer_headers():
    return TEST_USERS["second_grants_officer_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def second_adjudicator_headers():
    return TEST_USERS["second_adjudicator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def applicant_agent_headers():
    """Shared ApplicantAgent constant.

    Only for calls that never resolve an owning applicant; anything
    ownership-gated must use make_applicant_agent_headers(applicant_id).
    """
    return TEST_USERS["applicant_agent_headers"]
