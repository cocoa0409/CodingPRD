"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def group_admin_headers():
    return TEST_USERS["group_admin_headers"]


@pytest.fixture
def hospitalist_headers():
    return TEST_USERS["hospitalist_headers"]


@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]
