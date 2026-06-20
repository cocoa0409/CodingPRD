"""Pytest fixtures exposing test_helpers infrastructure for the Donor-Advised Fund API."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sponsor_admin_headers():
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def contribution_admin_headers():
    return TEST_USERS["contribution_admin_headers"]


@pytest.fixture
def donor_advisor_headers():
    return TEST_USERS["donor_advisor_headers"]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS["grant_officer_headers"]
