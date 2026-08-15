"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def hr_partner_headers():
    return TEST_USERS["hr_partner_headers"]


@pytest.fixture
def hr_partner_approver_headers():
    return TEST_USERS["hr_partner_approver_headers"]


@pytest.fixture
def hr_reviewer_headers():
    return TEST_USERS["hr_reviewer_headers"]


@pytest.fixture
def hr_director_headers():
    return TEST_USERS["hr_director_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]


@pytest.fixture
def payroll_approver_headers():
    return TEST_USERS["payroll_approver_headers"]


@pytest.fixture
def it_operator_headers():
    return TEST_USERS["it_operator_headers"]


@pytest.fixture
def it_verifier_headers():
    return TEST_USERS["it_verifier_headers"]


@pytest.fixture
def it_manager_headers():
    return TEST_USERS["it_manager_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def asset_clerk_headers():
    return TEST_USERS["asset_clerk_headers"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]
