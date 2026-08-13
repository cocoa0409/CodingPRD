"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["wire_ops_admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["wire_operator_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["wire_approver_headers"]


@pytest.fixture
def approver2_headers():
    return TEST_USERS["wire_approver_2_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["sanctions_screener_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def repair_specialist_headers():
    return TEST_USERS["repair_specialist_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["wire_investigator_headers"]


@pytest.fixture
def beneficiary_bank_headers():
    return TEST_USERS["beneficiary_bank_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
