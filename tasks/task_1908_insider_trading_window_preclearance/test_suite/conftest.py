"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def legal_admin_headers():
    return TEST_USERS["legal_admin_headers"]


@pytest.fixture
def insider_headers():
    return TEST_USERS["insider_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]
