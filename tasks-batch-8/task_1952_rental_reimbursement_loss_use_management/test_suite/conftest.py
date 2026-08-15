"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed externally; tests assume the API is already
reachable at API_BASE_URL and that the database is empty at test start.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def rental_desk_agent_headers():
    return TEST_USERS["rental_desk_agent_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def settlement_approver_headers():
    return TEST_USERS["settlement_approver_headers"]


@pytest.fixture
def repair_shop_headers():
    return TEST_USERS["repair_shop_headers"]


@pytest.fixture
def rental_partner_headers():
    return TEST_USERS["rental_partner_headers"]


@pytest.fixture
def recovery_specialist_headers():
    return TEST_USERS["recovery_specialist_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
