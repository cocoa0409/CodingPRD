"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def closing_officer_headers():
    return TEST_USERS["closing_officer_headers"]


@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def listing_agent_headers():
    """Fallback ListingAgent headers — only for probes that do not exercise
    ownership. Ownership-gated calls must use make_listing_agent_headers."""
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def selling_agent_headers():
    """Fallback SellingAgent headers — only for probes that do not exercise
    ownership. Ownership-gated calls must use make_selling_agent_headers."""
    return TEST_USERS["selling_agent_headers"]
