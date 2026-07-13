"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def assessor_headers():
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def credit_inspector_headers():
    return TEST_USERS["credit_inspector_headers"]


@pytest.fixture
def stormwater_admin_headers():
    return TEST_USERS["stormwater_admin_headers"]


@pytest.fixture
def property_owner_headers():
    return TEST_USERS["property_owner_headers"]
