"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_employee_headers,
    make_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def medical_officer_headers():
    return TEST_USERS["medical_officer_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def appeal_officer_headers():
    return TEST_USERS["appeal_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def employee_headers_for():
    """Factory: Employee headers bound to a real Employee row id."""
    return make_employee_headers


@pytest.fixture
def manager_headers_for():
    """Factory: Manager headers bound to a real Employee row id."""
    return make_manager_headers
