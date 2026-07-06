"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def auth_specialist_headers():
    return TEST_USERS["auth_specialist_headers"]


@pytest.fixture
def visiting_nurse_headers():
    return TEST_USERS["visiting_nurse_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def biller_headers():
    return TEST_USERS["biller_headers"]


@pytest.fixture
def warehouse_clerk_headers():
    return TEST_USERS["warehouse_clerk_headers"]
