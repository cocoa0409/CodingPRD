"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def billing_partner_headers():
    return TEST_USERS["billing_partner_headers"]


@pytest.fixture
def managing_partner_headers():
    return TEST_USERS["managing_partner_headers"]


@pytest.fixture
def timekeeper_headers():
    return TEST_USERS["timekeeper_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]
