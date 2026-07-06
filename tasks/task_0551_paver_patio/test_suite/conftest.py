"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before each test (so every test sees an empty database).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def design_headers():
    return TEST_USERS["design_consultant_headers"]


@pytest.fixture
def pm_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
