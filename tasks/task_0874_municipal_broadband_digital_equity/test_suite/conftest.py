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
def compliance_analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customer_care_headers():
    return TEST_USERS["customer_care_headers"]


@pytest.fixture
def eligibility_worker_headers():
    return TEST_USERS["eligibility_worker_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def field_tech_headers():
    return TEST_USERS["field_tech_headers"]


@pytest.fixture
def noc_operator_headers():
    return TEST_USERS["noc_operator_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]
