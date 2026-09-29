"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def product_engineer_headers():
    return TEST_USERS["product_engineer_headers"]


@pytest.fixture
def product_engineer_alt_headers():
    return TEST_USERS["product_engineer_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def order_planner_headers():
    return TEST_USERS["order_planner_headers"]


@pytest.fixture
def service_ops_admin_headers():
    return TEST_USERS["service_ops_admin_headers"]


@pytest.fixture
def facility_manager_headers():
    """Unbound FacilityManager headers. Only safe where no ownership check is
    reached; ownership-gated calls must build headers from the facility id."""
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def service_partner_tech_headers():
    """Unbound ServicePartnerTech headers. Only safe where no ownership check is
    reached; ownership-gated calls must build headers from the partner id."""
    return TEST_USERS["service_partner_tech_headers"]
