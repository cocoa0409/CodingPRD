"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def engagement_manager_headers():
    return TEST_USERS["engagement_manager_headers"]


@pytest.fixture
def classification_analyst_headers():
    return TEST_USERS["classification_analyst_headers"]


@pytest.fixture
def hr_approver_headers():
    return TEST_USERS["hr_approver_headers"]


@pytest.fixture
def legal_approver_headers():
    return TEST_USERS["legal_approver_headers"]


@pytest.fixture
def compliance_board_member_headers():
    return TEST_USERS["compliance_board_member_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def tax_reporting_specialist_headers():
    return TEST_USERS["tax_reporting_specialist_headers"]


@pytest.fixture
def agency_liaison_headers():
    return TEST_USERS["agency_liaison_headers"]
