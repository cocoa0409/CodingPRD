"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def call_center_headers():
    return TEST_USERS["call_center_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def excavator_headers():
    return TEST_USERS["excavator_headers"]


@pytest.fixture
def facility_owner_headers():
    return TEST_USERS["facility_owner_headers"]


@pytest.fixture
def locate_tech_headers():
    return TEST_USERS["locate_tech_headers"]
