"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def carrier_rep_headers():
    return TEST_USERS["carrier_rep_headers"]
