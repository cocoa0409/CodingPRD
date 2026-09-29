"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def intake_clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def technician_2_headers():
    return TEST_USERS["technician_2_headers"]


@pytest.fixture
def certifying_inspector_headers():
    return TEST_USERS["certifying_inspector_headers"]


@pytest.fixture
def certifying_inspector_2_headers():
    return TEST_USERS["certifying_inspector_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def customer_contact_headers():
    """Fallback CustomerContact headers for tests that do not exercise account
    scoping. Scoped reads must use make_customer_contact_headers(account_id)."""
    return TEST_USERS["customer_contact_headers"]
