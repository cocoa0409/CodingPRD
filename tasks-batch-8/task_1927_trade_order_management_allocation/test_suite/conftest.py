"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def trader_headers():
    return TEST_USERS["trader_headers"]


@pytest.fixture
def execution_desk_headers():
    return TEST_USERS["execution_desk_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def settlement_ops_headers():
    return TEST_USERS["settlement_ops_headers"]


@pytest.fixture
def desk_admin_headers():
    return TEST_USERS["desk_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
