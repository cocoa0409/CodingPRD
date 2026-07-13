"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def gate_operator_headers():
    return TEST_USERS["gate_operator_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def hauler_headers():
    return TEST_USERS["hauler_headers"]
