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
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def recruiter_2_headers():
    return TEST_USERS["recruiter_2_headers"]


@pytest.fixture
def hiring_manager_headers():
    return TEST_USERS["hiring_manager_headers"]


@pytest.fixture
def hiring_manager_2_headers():
    return TEST_USERS["hiring_manager_2_headers"]


@pytest.fixture
def comp_approver_headers():
    return TEST_USERS["comp_approver_headers"]


@pytest.fixture
def comp_approver_2_headers():
    return TEST_USERS["comp_approver_2_headers"]


@pytest.fixture
def vp_headers():
    return TEST_USERS["vp_headers"]


@pytest.fixture
def vp_2_headers():
    return TEST_USERS["vp_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def payroll_officer_headers():
    return TEST_USERS["payroll_officer_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]
