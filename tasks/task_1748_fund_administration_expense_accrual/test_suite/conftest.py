"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fund_accountant_headers():
    return TEST_USERS["fund_accountant_headers"]


@pytest.fixture
def fund_controller_headers():
    return TEST_USERS["fund_controller_headers"]


@pytest.fixture
def pricing_committee_headers():
    return TEST_USERS["pricing_committee_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
