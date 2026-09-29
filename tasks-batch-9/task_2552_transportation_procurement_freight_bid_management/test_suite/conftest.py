"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import DEFAULT_CLOCK
from test_helpers import set_clock as _set_clock


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def category_manager_headers():
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def category_manager_alt_headers():
    return TEST_USERS["category_manager_alt_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def contract_admin_alt_headers():
    return TEST_USERS["contract_admin_alt_headers"]


@pytest.fixture
def pinned_clock():
    """Pins the logical clock to the default instant before the test body runs."""
    _set_clock(DEFAULT_CLOCK)
    return DEFAULT_CLOCK
