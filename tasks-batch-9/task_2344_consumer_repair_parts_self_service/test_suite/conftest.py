"""Pytest fixtures exposing the shared test_helpers infrastructure.

The runner relaunches the API server with an empty database before every test, so
every fixture below is stateless: it hands back identity headers or the API client
and never seeds data.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin"]


@pytest.fixture
def safety_reviewer_headers():
    return TEST_USERS["safety_reviewer"]


@pytest.fixture
def documentation_engineer_headers():
    return TEST_USERS["documentation_engineer"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer"]


@pytest.fixture
def self_repair_customer_headers():
    return TEST_USERS["self_repair_customer"]


@pytest.fixture
def repair_provider_tech_headers():
    return TEST_USERS["repair_provider_tech"]


@pytest.fixture
def failure_analysis_engineer_headers():
    return TEST_USERS["failure_analysis_engineer"]
