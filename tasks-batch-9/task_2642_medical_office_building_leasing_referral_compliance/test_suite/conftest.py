"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def portfolio_admin_headers():
    """PortfolioAdmin: registers buildings, suites, shared spaces and tenants."""
    return TEST_USERS["portfolio_admin_headers"]


@pytest.fixture
def leasing_agent_headers():
    """LeasingAgent: drafts, amends, submits, executes leases and opens TI projects."""
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    """ComplianceOfficer: appraisals, certification, mix freeze, cases, write-offs."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    """A second ComplianceOfficer identity, for the two duty separations."""
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def property_manager_headers():
    """PropertyManager: commencement, termination, billing, parking, after-hours."""
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def facilities_engineer_headers():
    """FacilitiesEngineer: the two engineering reviews and project close-out."""
    return TEST_USERS["facilities_engineer_headers"]
