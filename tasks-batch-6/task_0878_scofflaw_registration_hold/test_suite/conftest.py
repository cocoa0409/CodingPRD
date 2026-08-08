"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def hearing_clerk_headers():
    return TEST_USERS["hearing_clerk_headers"]


@pytest.fixture
def collections_admin_headers():
    return TEST_USERS["collections_admin_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
