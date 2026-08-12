"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["ops_dispatcher_headers"]


@pytest.fixture
def crew_headers():
    return TEST_USERS["crew_lead_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]


@pytest.fixture
def subcontractor_headers():
    return TEST_USERS["subcontractor_headers"]
