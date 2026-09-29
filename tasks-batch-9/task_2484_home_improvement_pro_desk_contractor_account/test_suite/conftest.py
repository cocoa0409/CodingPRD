"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def contractor_admin_headers():
    """Fallback ContractorAdmin headers for probes that never reach an ownership check."""
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def pro_desk_associate_headers():
    return TEST_USERS["pro_desk_associate_headers"]


@pytest.fixture
def second_pro_desk_associate_headers():
    return TEST_USERS["second_pro_desk_associate_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def second_credit_manager_headers():
    return TEST_USERS["second_credit_manager_headers"]


@pytest.fixture
def store_operations_headers():
    return TEST_USERS["store_operations_headers"]


@pytest.fixture
def tax_compliance_officer_headers():
    return TEST_USERS["tax_compliance_officer_headers"]
