"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def cardholder_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["cardholder_headers"]


@pytest.fixture
def eligibility_specialist_headers():
    return TEST_USERS["eligibility_specialist_headers"]


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def merchant_operator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["merchant_operator_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]
