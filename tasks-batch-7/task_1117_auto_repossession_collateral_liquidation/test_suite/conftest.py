"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def recovery_manager_headers():
    return TEST_USERS["recovery_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def repo_agent_headers():
    return TEST_USERS["repo_agent_headers"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]
