"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def privacy_admin_headers():
    return TEST_USERS["privacy_admin_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def visitor_headers():
    return TEST_USERS["visitor_headers"]
