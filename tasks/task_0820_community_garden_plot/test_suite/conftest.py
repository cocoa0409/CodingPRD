"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (the API server is restarted before every test → empty DB each time).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def gardener_headers():
    return TEST_USERS["gardener_headers"]
