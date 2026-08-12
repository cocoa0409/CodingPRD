"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def field_contractor_headers():
    return TEST_USERS["field_contractor_headers"]


@pytest.fixture
def quality_auditor_headers():
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def ami_operator_headers():
    return TEST_USERS["ami_operator_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]
