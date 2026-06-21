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
def loan_servicer_headers():
    return TEST_USERS["loan_servicer_headers"]


@pytest.fixture
def loan_servicer_b_headers():
    return TEST_USERS["loan_servicer_b_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]
