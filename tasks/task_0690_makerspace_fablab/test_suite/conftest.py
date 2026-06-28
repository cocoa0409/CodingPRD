"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by prd-bench-local-runner, which restarts the
API server before every test. PYTHONPATH is set by the runner so test_helpers
is importable.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def member_headers():
    """Shared fallback Member headers — for non-ownership tests only."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def staff_headers():
    """Shared fallback StaffInstructor headers — for non-ownership tests only."""
    return TEST_USERS["staff_headers"]
