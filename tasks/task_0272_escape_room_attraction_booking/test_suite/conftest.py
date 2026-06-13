"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the server
lifecycle (restarting the server before every individual test).
"""
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
def venue_manager_headers():
    return TEST_USERS["venue_manager_headers"]


@pytest.fixture
def game_master_headers():
    return TEST_USERS["game_master_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
