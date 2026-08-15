"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def case_analyst_headers():
    return TEST_USERS["case_analyst_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def member_services_rep_headers():
    return TEST_USERS["member_services_rep_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def claims_processor_headers():
    return TEST_USERS["claims_processor_headers"]
