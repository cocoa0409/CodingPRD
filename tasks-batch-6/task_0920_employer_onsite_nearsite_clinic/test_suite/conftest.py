"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def clinic_manager_headers():
    return TEST_USERS["clinic_manager_headers"]


@pytest.fixture
def payroll_processor_headers():
    return TEST_USERS["payroll_processor_headers"]
