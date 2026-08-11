"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["site_clerk_headers"]


@pytest.fixture
def clerk2_headers():
    return TEST_USERS["site_clerk_2_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]
