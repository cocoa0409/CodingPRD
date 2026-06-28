"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def creditor_rep_headers():
    return TEST_USERS["creditor_rep_headers"]
