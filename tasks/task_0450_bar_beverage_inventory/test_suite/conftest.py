"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; test_helpers is importable
directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def purchasing_agent_headers():
    return TEST_USERS["purchasing_agent_headers"]


@pytest.fixture
def bar_manager_headers():
    return TEST_USERS["bar_manager_headers"]
