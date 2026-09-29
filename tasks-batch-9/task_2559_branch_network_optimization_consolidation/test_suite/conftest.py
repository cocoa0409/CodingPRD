"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def strategist_headers():
    return TEST_USERS["strategist_headers"]


@pytest.fixture
def second_strategist_headers():
    return TEST_USERS["second_strategist_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def second_approver_headers():
    return TEST_USERS["second_approver_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def hr_headers():
    return TEST_USERS["hr_headers"]


@pytest.fixture
def real_estate_headers():
    return TEST_USERS["real_estate_headers"]


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]
