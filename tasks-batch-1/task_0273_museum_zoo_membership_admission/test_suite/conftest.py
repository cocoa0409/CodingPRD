"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and injects
API_BASE_URL so the session-scoped client targets the running server.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["membership_admin_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def gate_scanner_headers():
    return TEST_USERS["gate_scanner_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]
