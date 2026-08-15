"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def cardholder_headers():
    return TEST_USERS["cardholder_headers"]


@pytest.fixture
def intake_agent_headers():
    return TEST_USERS["intake_agent_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def chargeback_analyst_headers():
    return TEST_USERS["chargeback_analyst_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def bank_admin_headers():
    return TEST_USERS["bank_admin_headers"]
