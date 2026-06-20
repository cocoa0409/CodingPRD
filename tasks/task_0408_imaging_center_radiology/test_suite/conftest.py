"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["scheduling_clerk_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def technologist_headers():
    return TEST_USERS["technologist_headers"]


@pytest.fixture
def radiologist_headers():
    return TEST_USERS["radiologist_headers"]
