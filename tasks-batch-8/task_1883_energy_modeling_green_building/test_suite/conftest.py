"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def project_admin_headers():
    """Shared ProjectAdministrator headers — only for calls that are not
    ownership-gated. For administrator-recorded calls use
    make_project_administrator_headers(member_id)."""
    return TEST_USERS["project_admin_headers"]


@pytest.fixture
def modeler_headers():
    """Shared EnergyModeler headers — only for non-ownership tests."""
    return TEST_USERS["modeler_headers"]


@pytest.fixture
def doc_specialist_headers():
    """Shared DocumentationSpecialist headers — only for non-ownership tests."""
    return TEST_USERS["doc_specialist_headers"]


@pytest.fixture
def cx_agent_headers():
    """Shared CommissioningAgent headers — only for non-ownership tests."""
    return TEST_USERS["cx_agent_headers"]
