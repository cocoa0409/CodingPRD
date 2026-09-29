"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]


@pytest.fixture
def title_officer_headers():
    return TEST_USERS["title_officer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["auction_ops_headers"]


@pytest.fixture
def ops_closer_headers():
    """The operator that hammers lots down; recorded in `closed_by_user_id`."""
    return TEST_USERS["auction_ops_closer_headers"]


@pytest.fixture
def ops_contract_headers():
    """A different operator, required by the four-eyes rule on contract execution."""
    return TEST_USERS["auction_ops_contract_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
