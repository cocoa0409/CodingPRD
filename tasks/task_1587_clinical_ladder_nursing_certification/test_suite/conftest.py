"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def nurse_headers():
    """Shared Nurse headers — for non-ownership-gated calls only."""
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def payroll_officer_headers():
    return TEST_USERS["payroll_officer_headers"]


@pytest.fixture
def retention_analyst_headers():
    return TEST_USERS["retention_analyst_headers"]
