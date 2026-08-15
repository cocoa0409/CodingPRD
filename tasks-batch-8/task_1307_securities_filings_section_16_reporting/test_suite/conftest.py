"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def filing_coordinator_headers():
    return TEST_USERS["filing_coordinator_headers"]


@pytest.fixture
def filing_agent_headers():
    return TEST_USERS["filing_agent_headers"]


@pytest.fixture
def equity_plan_admin_headers():
    return TEST_USERS["equity_plan_admin_headers"]


@pytest.fixture
def reporting_insider_headers():
    return TEST_USERS["reporting_insider_headers"]
