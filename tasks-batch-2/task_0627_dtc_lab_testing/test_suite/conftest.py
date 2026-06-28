"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def catalog_admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def ordering_physician_headers():
    return TEST_USERS["ordering_physician_headers"]


@pytest.fixture
def phlebotomy_tech_headers():
    return TEST_USERS["phlebotomy_tech_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def lab_tech_2_headers():
    return TEST_USERS["lab_tech_2_headers"]
