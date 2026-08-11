"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["pm_headers"]


@pytest.fixture
def pm2_headers():
    return TEST_USERS["pm2_headers"]


@pytest.fixture
def exec_headers():
    return TEST_USERS["exec_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
