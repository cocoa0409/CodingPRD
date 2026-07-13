"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and manages the server
lifecycle (a fresh, empty-database server is launched before every individual test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def nurse_headers():
    """Shared HomeVisitNurse header — for non-ownership tests only (RBAC denials etc.)."""
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def supervisor_headers():
    """Shared Supervisor header — for non-ownership tests only."""
    return TEST_USERS["supervisor_headers"]
