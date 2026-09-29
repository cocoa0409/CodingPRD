"""Pytest fixtures exposing the test_helpers infrastructure to every test file."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def credit_officer_headers():
    """Headers for an opaque CreditOfficer operator."""
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def credit_risk_manager_headers():
    """Headers for an opaque CreditRiskManager operator."""
    return TEST_USERS["credit_risk_manager_headers"]


@pytest.fixture
def credit_risk_manager_2_headers():
    """Headers for a second, distinct CreditRiskManager operator."""
    return TEST_USERS["credit_risk_manager_2_headers"]


@pytest.fixture
def field_auditor_headers():
    """Headers for an opaque FieldAuditor operator."""
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def field_auditor_2_headers():
    """Headers for a second, distinct FieldAuditor operator."""
    return TEST_USERS["field_auditor_2_headers"]


@pytest.fixture
def audit_manager_headers():
    """Headers for an opaque AuditManager operator."""
    return TEST_USERS["audit_manager_headers"]


@pytest.fixture
def audit_manager_2_headers():
    """Headers for a second, distinct AuditManager operator."""
    return TEST_USERS["audit_manager_2_headers"]


@pytest.fixture
def system_operator_headers():
    """Headers for an opaque SystemOperator operator."""
    return TEST_USERS["system_operator_headers"]
