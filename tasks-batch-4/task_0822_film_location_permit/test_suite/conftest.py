"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def production_company_headers():
    return TEST_USERS["production_company_headers"]


@pytest.fixture
def department_reviewer_headers():
    return TEST_USERS["department_reviewer_headers"]


@pytest.fixture
def field_officer_headers():
    return TEST_USERS["field_officer_headers"]
