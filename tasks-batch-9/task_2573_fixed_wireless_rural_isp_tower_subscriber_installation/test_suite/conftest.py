"""Shared pytest fixtures.

The harness starts a fresh server with an empty database before each test and
exports `API_BASE_URL`, so nothing here needs to manage lifecycle or clean up.
"""

import pytest

from test_helpers import api_client as _api_client
from test_helpers.test_users import (
    BILLING_ADMIN,
    CAPACITY_PLANNER,
    FIELD_TECH,
    FINANCE_APPROVER,
    NETWORK_ENGINEER,
    SALES_AGENT,
    make_subscriber_headers,
)


@pytest.fixture
def api():
    """The endpoint-per-method client from `test_helpers.api_client`."""
    return _api_client


@pytest.fixture
def network_engineer():
    return NETWORK_ENGINEER


@pytest.fixture
def capacity_planner():
    return CAPACITY_PLANNER


@pytest.fixture
def sales_agent():
    return SALES_AGENT


@pytest.fixture
def field_tech():
    return FIELD_TECH


@pytest.fixture
def billing_admin():
    return BILLING_ADMIN


@pytest.fixture
def finance_approver():
    return FINANCE_APPROVER


@pytest.fixture
def subscriber_headers():
    """Builder for the `Subscriber` role, whose `X-User-ID` is the account's own id."""
    return make_subscriber_headers
