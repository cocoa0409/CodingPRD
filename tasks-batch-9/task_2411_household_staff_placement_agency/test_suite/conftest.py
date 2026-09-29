"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def agency_principal_headers():
    return TEST_USERS["agency_principal_headers"]


@pytest.fixture
def placement_consultant_headers():
    return TEST_USERS["placement_consultant_headers"]


@pytest.fixture
def vetting_specialist_headers():
    return TEST_USERS["vetting_specialist_headers"]


@pytest.fixture
def vetting_verifier_headers():
    return TEST_USERS["vetting_verifier_headers"]


@pytest.fixture
def billing_administrator_headers():
    return TEST_USERS["billing_administrator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_resolver_headers():
    return TEST_USERS["compliance_resolver_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]
