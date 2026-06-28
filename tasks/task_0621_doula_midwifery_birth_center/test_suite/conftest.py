"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so test_helpers is importable) and the server
lifecycle. These fixtures merely surface the API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def midwife_headers():
    return TEST_USERS["midwife_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["center_admin_headers"]
