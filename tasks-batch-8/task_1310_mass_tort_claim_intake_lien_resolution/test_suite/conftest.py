"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def records_analyst_headers():
    return TEST_USERS["records_analyst_headers"]


@pytest.fixture
def lien_analyst_headers():
    return TEST_USERS["lien_analyst_headers"]


@pytest.fixture
def disbursement_approver_headers():
    return TEST_USERS["disbursement_approver_headers"]


@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]
