"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plan_administrator_headers():
    return TEST_USERS["plan_administrator_headers"]


@pytest.fixture
def compliance_examiner_headers():
    return TEST_USERS["compliance_examiner_headers"]


@pytest.fixture
def second_compliance_examiner_headers():
    return TEST_USERS["second_compliance_examiner_headers"]


@pytest.fixture
def servicing_carrier_headers():
    return TEST_USERS["servicing_carrier_headers"]


@pytest.fixture
def producer_agent_headers():
    return TEST_USERS["producer_agent_headers"]
