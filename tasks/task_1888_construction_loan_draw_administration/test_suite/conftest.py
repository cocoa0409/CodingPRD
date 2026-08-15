"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def lender_admin_headers():
    return TEST_USERS["lender_admin_headers"]


@pytest.fixture
def draw_processor_headers():
    return TEST_USERS["draw_processor_headers"]


@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def loan_servicer_headers():
    return TEST_USERS["loan_servicer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def borrower_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["borrower_headers"]
