"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def payer_admin_headers():
    return TEST_USERS["payer_admin_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def attribution_analyst_headers():
    return TEST_USERS["attribution_analyst_headers"]


@pytest.fixture
def actuary_analyst_headers():
    return TEST_USERS["actuary_analyst_headers"]


@pytest.fixture
def quality_analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def claims_processor_headers():
    return TEST_USERS["claims_processor_headers"]


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def dispute_adjudicator_headers():
    return TEST_USERS["dispute_adjudicator_headers"]


@pytest.fixture
def payment_ops_headers():
    return TEST_USERS["payment_ops_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def practice_group_rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["practice_group_rep_headers"]
