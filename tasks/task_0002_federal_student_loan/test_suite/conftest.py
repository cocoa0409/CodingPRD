"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def loan_servicer_headers():
    return TEST_USERS["loan_servicer_headers"]


@pytest.fixture
def collections_agent_headers():
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def borrower_headers():
    """Fallback Borrower headers — DO NOT use for ownership-gated calls;
    use make_borrower_headers(borrower['id']) instead."""
    return TEST_USERS["borrower_headers"]
