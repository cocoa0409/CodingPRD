"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def acquirer_ops_headers():
    """Only safe where the call fails before the ownership comparison of PRD 2.1;
    otherwise build headers from the real acquirer id."""
    return TEST_USERS["acquirer_ops_headers"]


@pytest.fixture
def category_analyst_headers():
    return TEST_USERS["category_analyst_headers"]


@pytest.fixture
def second_category_analyst_headers():
    return TEST_USERS["second_category_analyst_headers"]


@pytest.fixture
def category_approver_headers():
    return TEST_USERS["category_approver_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def second_compliance_auditor_headers():
    return TEST_USERS["second_compliance_auditor_headers"]
