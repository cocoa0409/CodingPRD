"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def weigh_master_headers():
    return TEST_USERS["weigh_master_headers"]


@pytest.fixture
def payout_clerk_headers():
    return TEST_USERS["payout_clerk_headers"]


@pytest.fixture
def yard_manager_headers():
    return TEST_USERS["yard_manager_headers"]


@pytest.fixture
def settlement_accountant_headers():
    return TEST_USERS["settlement_accountant_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
