"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and restarts it before every test,
so each test starts against an empty database.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def coordinator_headers() -> dict:
    return TEST_USERS["program_coordinator_headers"]
