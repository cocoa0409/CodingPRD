"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ehs_admin_headers():
    return TEST_USERS["ehs_admin_headers"]


@pytest.fixture
def vending_tech_headers():
    return TEST_USERS["vending_tech_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
