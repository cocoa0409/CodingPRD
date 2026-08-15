"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ehs_manager_headers():
    return TEST_USERS["ehs_manager_headers"]


@pytest.fixture
def ehs_auditor_headers():
    return TEST_USERS["ehs_auditor_headers"]


@pytest.fixture
def authorized_employee_headers():
    return TEST_USERS["authorized_employee_headers"]
