"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable without sys.path
hacks, and it owns the server lifecycle (restarting before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def barn_manager_headers():
    return TEST_USERS["barn_manager_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def service_provider_headers():
    return TEST_USERS["service_provider_headers"]
