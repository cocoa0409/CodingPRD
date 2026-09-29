"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def store_admin_headers():
    """StoreAdmin — departments, catalogue seeding and the logical clock."""
    return TEST_USERS["store_admin_headers"]


@pytest.fixture
def meat_cutter_headers():
    """MeatCutter — receiving, the cutting bench, trim, the grinder, fills,
    staging and temperature readings."""
    return TEST_USERS["meat_cutter_headers"]


@pytest.fixture
def second_meat_cutter_headers():
    """A second MeatCutter operator, for segregation-of-duties paths."""
    return TEST_USERS["second_meat_cutter_headers"]


@pytest.fixture
def meat_manager_headers():
    """MeatManager — approvals, price activation, the case-plan lifecycle,
    shrink write-offs, aborts, escalation, forfeiture and posting."""
    return TEST_USERS["meat_manager_headers"]


@pytest.fixture
def second_meat_manager_headers():
    """A second MeatManager operator, for segregation-of-duties paths."""
    return TEST_USERS["second_meat_manager_headers"]


@pytest.fixture
def pricing_analyst_headers():
    """PricingAnalyst — provisional proposals, markdowns and reconciliations."""
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def service_clerk_headers():
    """ServiceClerk — customer pre-orders and temperature readings."""
    return TEST_USERS["service_clerk_headers"]
