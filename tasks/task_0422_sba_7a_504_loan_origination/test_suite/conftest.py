"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def loan_officer_headers():
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def credit_approver_headers():
    return TEST_USERS["credit_approver_headers"]


@pytest.fixture
def sba_officer_headers():
    return TEST_USERS["sba_officer_headers"]


@pytest.fixture
def investor_servicer_headers():
    return TEST_USERS["investor_servicer_headers"]
