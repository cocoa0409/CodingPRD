"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def clinic_coordinator_headers():
    return TEST_USERS["clinic_coordinator_headers"]


@pytest.fixture
def sleep_physician_headers():
    return TEST_USERS["sleep_physician_headers"]


@pytest.fixture
def dentist_headers():
    return TEST_USERS["dentist_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
