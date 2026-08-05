"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def leaseholder_headers():
    return TEST_USERS["leaseholder_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
