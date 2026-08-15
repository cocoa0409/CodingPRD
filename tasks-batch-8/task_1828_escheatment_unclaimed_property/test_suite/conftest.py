"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def holder_admin_headers():
    return TEST_USERS["holder_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def state_auditor_headers():
    return TEST_USERS["state_auditor_headers"]


@pytest.fixture
def treasury_ops_headers():
    return TEST_USERS["treasury_ops_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def claims_approver_headers():
    return TEST_USERS["claims_approver_headers"]


@pytest.fixture
def reader_headers():
    return TEST_USERS["reader_headers"]
