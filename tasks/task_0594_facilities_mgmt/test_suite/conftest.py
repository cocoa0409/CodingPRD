"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def finance_approver_headers():
    return TEST_USERS["finance_approver_headers"]


@pytest.fixture
def sustainability_analyst_headers():
    return TEST_USERS["sustainability_analyst_headers"]


@pytest.fixture
def vendor_tech_headers():
    """Fallback VendorTech identity. Ownership-gated calls must instead use
    make_vendor_tech_headers(vendor["id"])."""
    return TEST_USERS["vendor_tech_headers"]


@pytest.fixture
def tenant_rep_headers():
    """Fallback TenantRep identity. Ownership-gated calls must instead use
    make_tenant_rep_headers(lease["id"])."""
    return TEST_USERS["tenant_rep_headers"]
