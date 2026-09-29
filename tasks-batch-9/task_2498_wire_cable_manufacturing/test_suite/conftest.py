"""Shared pytest fixtures for the wire and cable manufacturing suite.

The runner starts a fresh server before every test, so each test owns an empty
database and every precondition is built from scratch through declared
endpoints. That is why the API client is session-scoped (it is stateless) while
everything that touches data lives in the test body or in ``test_helpers``.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The typed API client, one instance for the whole session."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def procurement_buyer_headers():
    return TEST_USERS["procurement_buyer_headers"]


@pytest.fixture
def process_engineer_headers():
    return TEST_USERS["process_engineer_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
