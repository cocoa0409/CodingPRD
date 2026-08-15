"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def cra_officer_headers():
    return TEST_USERS["cra_officer_headers"]


@pytest.fixture
def compliance_analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def qualification_reviewer_headers():
    return TEST_USERS["qualification_reviewer_headers"]


@pytest.fixture
def bank_examiner_headers():
    return TEST_USERS["bank_examiner_headers"]


@pytest.fixture
def bank_executive_headers():
    return TEST_USERS["bank_executive_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
