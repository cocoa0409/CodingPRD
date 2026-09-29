"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def project_operator_headers():
    return TEST_USERS["project_operator_headers"]


@pytest.fixture
def pipeline_scheduler_headers():
    return TEST_USERS["pipeline_scheduler_headers"]


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def credit_verifier_headers():
    return TEST_USERS["credit_verifier_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def finance_controller_b_headers():
    return TEST_USERS["finance_controller_b_headers"]


@pytest.fixture
def dairy_partner_headers():
    return TEST_USERS["dairy_partner_headers"]
