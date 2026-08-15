"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def program_manager_2_headers():
    return TEST_USERS["program_manager_2_headers"]


@pytest.fixture
def qa_inspector_headers():
    return TEST_USERS["qa_inspector_headers"]


@pytest.fixture
def qa_inspector_2_headers():
    return TEST_USERS["qa_inspector_2_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def citizen_reporter_headers():
    return TEST_USERS["citizen_reporter_headers"]


@pytest.fixture
def citizen_reporter_2_headers():
    return TEST_USERS["citizen_reporter_2_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_2_headers():
    return TEST_USERS["auditor_2_headers"]


@pytest.fixture
def field_supervisor_headers():
    """Shared FieldSupervisor headers — only for calls that are NOT
    ownership-gated. For dispatch/complete/fail/resolve use
    make_field_supervisor_headers(crew["id"])."""
    return TEST_USERS["field_supervisor_headers"]
