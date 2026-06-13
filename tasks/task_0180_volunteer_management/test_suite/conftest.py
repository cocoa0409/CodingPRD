"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shift_coordinator_headers():
    return TEST_USERS["shift_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def corporate_sponsor_headers():
    return TEST_USERS["corporate_sponsor_headers"]


@pytest.fixture
def volunteer_headers():
    """Shared fallback Volunteer headers — only for non-ownership tests."""
    return TEST_USERS["volunteer_headers"]
