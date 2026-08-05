"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def dietitian_headers():
    return TEST_USERS["dietitian_headers"]


@pytest.fixture
def behavioral_health_headers():
    return TEST_USERS["behavioral_health_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def surgeon_headers():
    return TEST_USERS["surgeon_headers"]
