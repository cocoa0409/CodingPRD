"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pharmacist_a_headers():
    return TEST_USERS["pharmacist_a_headers"]


@pytest.fixture
def pharmacist_b_headers():
    return TEST_USERS["pharmacist_b_headers"]


@pytest.fixture
def pharmacy_tech_headers():
    return TEST_USERS["pharmacy_tech_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def insurance_adjuster_headers():
    return TEST_USERS["insurance_adjuster_headers"]


@pytest.fixture
def pharmacy_admin_headers():
    return TEST_USERS["pharmacy_admin_headers"]
