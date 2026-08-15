"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def client_user_headers():
    return TEST_USERS["client_user_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def qc_reviewer_headers():
    return TEST_USERS["qc_reviewer_headers"]
