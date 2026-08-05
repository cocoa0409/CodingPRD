"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def taxpayer_headers():
    return TEST_USERS["taxpayer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
