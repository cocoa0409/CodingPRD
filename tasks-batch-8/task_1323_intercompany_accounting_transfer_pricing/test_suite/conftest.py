"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def group_tax_admin_headers():
    return TEST_USERS["group_tax_admin_headers"]


@pytest.fixture
def tax_analyst_headers():
    return TEST_USERS["tax_analyst_headers"]


@pytest.fixture
def tax_manager_headers():
    return TEST_USERS["tax_manager_headers"]


@pytest.fixture
def transfer_pricing_lead_headers():
    return TEST_USERS["transfer_pricing_lead_headers"]


@pytest.fixture
def treasury_manager_headers():
    return TEST_USERS["treasury_manager_headers"]
