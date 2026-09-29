"""Pytest fixtures exposing the managed print services test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def account_manager_2_headers():
    return TEST_USERS["account_manager_2_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]


@pytest.fixture
def billing_analyst_2_headers():
    return TEST_USERS["billing_analyst_2_headers"]


@pytest.fixture
def fleet_ops_headers():
    return TEST_USERS["fleet_ops_headers"]


@pytest.fixture
def fleet_ops_2_headers():
    return TEST_USERS["fleet_ops_2_headers"]


@pytest.fixture
def field_technician_headers():
    """Shared FieldTechnician headers — only for calls that never reach an
    ownership check. Ownership-gated calls must use make_field_technician_headers()
    with the technician's own id."""
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def customer_admin_headers():
    """Shared CustomerAdmin headers — only for calls that never reach an
    ownership check. Ownership-gated calls must use make_customer_admin_headers()
    with the site's own id."""
    return TEST_USERS["customer_admin_headers"]
