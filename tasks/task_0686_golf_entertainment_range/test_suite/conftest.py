"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and server lifecycle.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def guest_headers():
    """Shared Guest fallback — for Guest calls that do NOT exercise ownership."""
    return TEST_USERS["guest_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def range_manager_headers():
    return TEST_USERS["range_manager_headers"]
