"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_customer_headers,
    make_prescriber_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin — reference data and the logical clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def compliance_headers():
    """The compliance desk, acting as operator co-alpha."""
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def compliance_second_headers():
    """A second compliance operator, co-bravo, for the two-person workflows."""
    return TEST_USERS["compliance_second_headers"]


@pytest.fixture
def fulfillment_headers():
    """Warehouse staff — substitution, shipping, delivery, auto-reorder run."""
    return TEST_USERS["fulfillment_headers"]


@pytest.fixture
def customer_headers():
    """A Customer identity that owns no row. Only safe where the call under test
    fails before any ownership comparison."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def prescriber_headers():
    """A Prescriber identity that owns no row. Only safe where the call under
    test fails before any ownership comparison."""
    return TEST_USERS["prescriber_headers"]


@pytest.fixture
def customer_headers_for():
    """Builder for the acting patient's headers, keyed on a real Customer id."""
    return make_customer_headers


@pytest.fixture
def prescriber_headers_for():
    """Builder for the acting provider's headers, keyed on a real Prescriber id."""
    return make_prescriber_headers
