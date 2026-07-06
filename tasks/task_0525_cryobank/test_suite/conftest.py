"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def screening_officer_headers():
    return TEST_USERS["screening_officer_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def catalog_manager_headers():
    return TEST_USERS["catalog_manager_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def recipient_headers():
    return TEST_USERS["recipient_headers"]
