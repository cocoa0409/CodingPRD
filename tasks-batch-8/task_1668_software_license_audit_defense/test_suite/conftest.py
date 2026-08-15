"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sam_manager_headers():
    return TEST_USERS["sam_manager_headers"]


@pytest.fixture
def it_analyst_headers():
    return TEST_USERS["it_analyst_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def procurement_lead_headers():
    return TEST_USERS["procurement_lead_headers"]


@pytest.fixture
def vendor_auditor_headers():
    return TEST_USERS["vendor_auditor_headers"]
