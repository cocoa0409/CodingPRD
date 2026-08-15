"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["inventory_technician_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_representative_headers"]
