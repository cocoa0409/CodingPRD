"""Pytest fixtures exposing the correspondent test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["counterparty_analyst"]


@pytest.fixture
def analyst_alt_headers():
    return TEST_USERS["counterparty_analyst_alt"]


@pytest.fixture
def qc_headers():
    return TEST_USERS["qc_reviewer"]


@pytest.fixture
def trader_headers():
    return TEST_USERS["lock_desk_trader"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["purchase_reviewer"]


@pytest.fixture
def reviewer_alt_headers():
    return TEST_USERS["purchase_reviewer_alt"]


@pytest.fixture
def reviewer_third_headers():
    return TEST_USERS["purchase_reviewer_third"]
