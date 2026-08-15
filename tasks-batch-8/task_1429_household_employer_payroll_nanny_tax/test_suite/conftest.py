"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def household_client_headers():
    return TEST_USERS["household_client_headers"]


@pytest.fixture
def worker_headers():
    return TEST_USERS["worker_headers"]
