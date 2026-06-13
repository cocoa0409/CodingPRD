"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restart before every test → empty DB per test).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def venue_admin_headers():
    return TEST_USERS["venue_admin_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
