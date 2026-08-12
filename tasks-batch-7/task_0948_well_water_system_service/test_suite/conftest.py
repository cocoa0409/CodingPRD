"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def officer_beta_headers():
    return TEST_USERS["compliance_officer_beta_headers"]


@pytest.fixture
def officer_bravo_headers():
    return TEST_USERS["compliance_officer_bravo_headers"]


@pytest.fixture
def technician_headers():
    """Unbound technician identity: only safe where no ownership gate runs."""
    return TEST_USERS["technician_headers"]


@pytest.fixture
def customer_headers():
    """Unbound customer identity: only safe where no ownership gate runs."""
    return TEST_USERS["customer_contact_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
