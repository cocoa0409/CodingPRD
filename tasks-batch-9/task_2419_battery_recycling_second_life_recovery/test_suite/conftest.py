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
def market_analyst_headers():
    return TEST_USERS["market_analyst_headers"]


@pytest.fixture
def intake_clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def plant_operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def triage_engineer_headers():
    return TEST_USERS["triage_engineer_headers"]


@pytest.fixture
def assay_technician_headers():
    return TEST_USERS["assay_technician_headers"]


@pytest.fixture
def settlement_accountant_headers():
    return TEST_USERS["settlement_accountant_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def supplier_rep_headers():
    """Fallback identity only — ownership-gated calls must build headers from
    the acting supplier's own id."""
    return TEST_USERS["supplier_rep_headers"]
