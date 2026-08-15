"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def foundation_admin_headers():
    return TEST_USERS["foundation_admin_headers"]


@pytest.fixture
def gift_officer_headers():
    return TEST_USERS["gift_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def program_officer_headers():
    return TEST_USERS["program_officer_headers"]


@pytest.fixture
def investment_manager_headers():
    return TEST_USERS["investment_manager_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
