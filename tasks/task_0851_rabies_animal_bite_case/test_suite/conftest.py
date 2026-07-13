"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def epidemiologist_headers():
    return TEST_USERS["epidemiologist_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def animal_control_officer_headers():
    return TEST_USERS["animal_control_officer_headers"]


@pytest.fixture
def health_dept_admin_headers():
    return TEST_USERS["health_dept_admin_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
