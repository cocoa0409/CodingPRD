"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def portfolio_admin_headers():
    return TEST_USERS["portfolio_admin_headers"]


@pytest.fixture
def innovation_lead_headers():
    return TEST_USERS["innovation_lead_headers"]


@pytest.fixture
def gate_chair_headers():
    return TEST_USERS["gate_chair_headers"]


@pytest.fixture
def functional_reviewer_headers():
    return TEST_USERS["functional_reviewer_headers"]


@pytest.fixture
def regulatory_approver_headers():
    return TEST_USERS["regulatory_approver_headers"]


@pytest.fixture
def rnd_lead_headers():
    return TEST_USERS["rnd_lead_headers"]


@pytest.fixture
def sales_account_manager_headers():
    return TEST_USERS["sales_account_manager_headers"]
