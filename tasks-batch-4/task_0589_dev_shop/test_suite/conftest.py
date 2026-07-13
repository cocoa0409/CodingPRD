"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def delivery_lead_headers():
    return TEST_USERS["delivery_lead_headers"]


@pytest.fixture
def delivery_lead_2_headers():
    return TEST_USERS["delivery_lead_2_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def engineer_2_headers():
    return TEST_USERS["engineer_2_headers"]


@pytest.fixture
def client_contact_headers():
    """Fallback ClientContact identity. Ownership-gated calls must instead build
    headers from the acting Client's id via make_client_contact_headers()."""
    return TEST_USERS["client_contact_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
