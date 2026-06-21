"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_loan_servicer_headers,
    make_compliance_officer_headers,
    make_borrower_headers,
    make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def loan_servicer_headers():
    return TEST_USERS["loan_servicer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def borrower_headers_shared():
    """Shared Borrower header constant. Use only for negative-path tests
    where the actual borrower_id doesn't matter (e.g., ownership-denial)."""
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def anonymous_headers():
    """Empty header dict — provokes ERR_UNAUTHENTICATED (PRD §2.1)."""
    return make_anonymous_headers()


@pytest.fixture
def headers_factory():
    """Factory exposing per-role builder functions so tests can mint
    per-entity headers (Borrower role requires the actual Borrower.id)."""
    return {
        "loan_servicer": make_loan_servicer_headers,
        "compliance_officer": make_compliance_officer_headers,
        "borrower": make_borrower_headers,
    }
