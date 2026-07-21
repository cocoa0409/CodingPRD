"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def claims_processor_headers():
    return TEST_USERS["claims_processor_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def dealer_headers():
    return TEST_USERS["dealer_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]
