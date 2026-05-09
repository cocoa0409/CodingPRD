"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_token_headers():
    return TEST_USERS["admin_token_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_b_headers():
    return TEST_USERS["reviewer_b_headers"]


@pytest.fixture
def payout_officer_headers():
    return TEST_USERS["payout_officer_headers"]


@pytest.fixture
def customer_headers():
    """Placeholder Customer headers — only safe for non-ownership tests
    (e.g., 400-on-bad-payload, 404 on missing claim, RBAC-only checks).
    For ownership-gated calls, use make_customer_headers(insured_party_id)
    so Policy.insured_party_id and Claim.claimant_id resolve to the same id."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def adjuster_headers():
    """Placeholder Adjuster headers — only safe for non-ownership tests
    (e.g., 400-on-bad-payload, RBAC, 404 on missing claim). For ownership-
    gated calls, use make_adjuster_headers(adjuster["id"])."""
    return TEST_USERS["adjuster_headers"]
