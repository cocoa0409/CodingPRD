"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def care_coordinator_headers():
    return TEST_USERS["care_coordinator_headers"]


@pytest.fixture
def paramedic_headers():
    return TEST_USERS["paramedic_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def payer_reviewer_headers():
    return TEST_USERS["payer_reviewer_headers"]
