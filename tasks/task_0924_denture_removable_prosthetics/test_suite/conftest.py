"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def prosthodontist_headers():
    return TEST_USERS["prosthodontist_headers"]


@pytest.fixture
def clinical_director_headers():
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def front_office_headers():
    return TEST_USERS["front_office_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
