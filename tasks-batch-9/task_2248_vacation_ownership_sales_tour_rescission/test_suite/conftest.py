"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def marketing_manager_headers():
    return TEST_USERS["marketing_manager_headers"]


@pytest.fixture
def gallery_manager_headers():
    return TEST_USERS["gallery_manager_headers"]


@pytest.fixture
def sales_representative_headers():
    """Placeholder representative identity — not valid for ownership-gated calls."""
    return TEST_USERS["sales_representative_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_bravo_headers():
    return TEST_USERS["compliance_officer_bravo_headers"]


@pytest.fixture
def contract_administrator_headers():
    return TEST_USERS["contract_administrator_headers"]


@pytest.fixture
def contract_admin_adjudicator_headers():
    return TEST_USERS["contract_admin_adjudicator_headers"]


@pytest.fixture
def contract_admin_disburser_headers():
    return TEST_USERS["contract_admin_disburser_headers"]


@pytest.fixture
def contract_admin_funder_headers():
    return TEST_USERS["contract_admin_funder_headers"]


@pytest.fixture
def contract_admin_underwriter_headers():
    return TEST_USERS["contract_admin_underwriter_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
