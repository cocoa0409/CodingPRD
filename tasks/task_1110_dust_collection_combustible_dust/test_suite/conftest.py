"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]


@pytest.fixture
def compliance_engineer_headers():
    return TEST_USERS["compliance_engineer_headers"]


@pytest.fixture
def safety_manager_headers():
    return TEST_USERS["safety_manager_headers"]


@pytest.fixture
def hot_work_performer_headers():
    return TEST_USERS["hot_work_performer_headers"]


@pytest.fixture
def housekeeping_auditor_headers():
    return TEST_USERS["housekeeping_auditor_headers"]


@pytest.fixture
def inspector_user_headers():
    return TEST_USERS["inspector_user_headers"]


@pytest.fixture
def incident_investigator_headers():
    return TEST_USERS["incident_investigator_headers"]
