"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests receive a session-scoped
API client plus per-role header fixtures. The server is restarted before every
test, so each test starts against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def ip_headers():
    return TEST_USERS["infection_preventionist_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["infection_control_director_headers"]


@pytest.fixture
def nurse_manager_headers():
    return TEST_USERS["unit_nurse_manager_headers"]


@pytest.fixture
def health_nurse_headers():
    return TEST_USERS["employee_health_nurse_headers"]
