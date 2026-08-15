"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def yard_master_headers():
    return TEST_USERS["yard_master_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def transfer_operator_headers():
    return TEST_USERS["transfer_operator_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def customer_rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_rep_headers"]
