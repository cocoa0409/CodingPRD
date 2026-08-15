"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def escrow_analyst_headers():
    return TEST_USERS["escrow_analyst_headers"]


@pytest.fixture
def escrow_analyst_2_headers():
    return TEST_USERS["escrow_analyst_2_headers"]


@pytest.fixture
def disbursement_processor_headers():
    return TEST_USERS["disbursement_processor_headers"]


@pytest.fixture
def disbursement_processor_2_headers():
    return TEST_USERS["disbursement_processor_2_headers"]


@pytest.fixture
def payee_verifier_headers():
    return TEST_USERS["payee_verifier_headers"]


@pytest.fixture
def payee_verifier_2_headers():
    return TEST_USERS["payee_verifier_2_headers"]


@pytest.fixture
def insurance_specialist_headers():
    return TEST_USERS["insurance_specialist_headers"]


@pytest.fixture
def borrower_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["borrower_headers"]
