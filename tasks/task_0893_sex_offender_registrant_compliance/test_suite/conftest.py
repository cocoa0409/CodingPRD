"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def registration_officer_headers():
    return TEST_USERS["registration_officer_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def registrant_headers():
    return TEST_USERS["registrant_headers"]
